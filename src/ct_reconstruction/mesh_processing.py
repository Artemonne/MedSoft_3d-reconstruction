"""Verified surface processing, with native hole filling isolated in a process."""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import numpy as np

from .errors import MeshError
from .models import Mesh
from .surface import from_pyvista, mesh_metrics, to_pyvista

_MIN_DECIMATABLE_COMPONENT_FACES = 500


def smooth_mesh(
    mesh: Mesh, *, iterations: int = 20, relaxation: float = 0.01
) -> Mesh:
    if iterations < 1 or not 0 < relaxation <= 1:
        raise MeshError("Некорректные параметры сглаживания")
    before = mesh_metrics(mesh)
    poly = to_pyvista(mesh)
    result = poly.smooth(
        n_iter=iterations,
        relaxation_factor=relaxation,
        boundary_smoothing=False,
        feature_smoothing=False,
    )
    processed = from_pyvista(
        result, source=mesh, operation=f"smooth({iterations},{relaxation:g})"
    )
    result_metrics = _ensure_usable(processed)
    _ensure_topology_preserved(before, result_metrics)
    return processed


def decimate_mesh(mesh: Mesh, *, reduction: float = 0.5) -> Mesh:
    if not 0 < reduction < 1:
        raise MeshError("Доля упрощения должна находиться между 0 и 1")
    before = mesh_metrics(mesh)
    poly = to_pyvista(mesh)
    if before["non_manifold_edges"]:
        result = _decimate_manifold_components(poly, reduction)
    else:
        result = poly.decimate_pro(
            reduction,
            preserve_topology=True,
            splitting=False,
            boundary_vertex_deletion=False,
        )
    processed = from_pyvista(
        result, source=mesh, operation=f"decimate({reduction:g})"
    )
    result_metrics = _ensure_usable(processed)
    _ensure_topology_preserved(before, result_metrics)
    if len(processed.faces) >= len(mesh.faces):
        raise MeshError("Упрощение не уменьшило число треугольников")
    return processed


def _decimate_manifold_components(poly, reduction: float):
    """Decimate only components that contain no non-manifold edge.

    VTK's decimators can multiply existing non-manifold junctions even with
    ``preserve_topology=True``.  Components containing such junctions are kept
    byte-for-byte topologically intact; the requested reduction is applied to
    the remaining components as far as their triangle count permits.
    """
    import pyvista as pv
    from vtkmodules.vtkFiltersCore import vtkAppendPolyData

    connected = poly.connectivity()
    faces = np.asarray(connected.faces, dtype=np.int64).reshape(-1, 4)[:, 1:]
    region_ids = np.asarray(connected.cell_data["RegionId"], dtype=np.int64)
    face_ids = np.arange(len(faces), dtype=np.int64)
    edges = np.sort(
        np.vstack((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)])),
        axis=1,
    )
    edge_face_ids = np.tile(face_ids, 3)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    sorted_edges = edges[order]
    _, first, counts = np.unique(
        sorted_edges, axis=0, return_index=True, return_counts=True
    )
    non_manifold_groups = np.flatnonzero(counts > 2)
    if not non_manifold_groups.size:
        return poly.decimate_pro(
            reduction,
            preserve_topology=True,
            splitting=False,
            boundary_vertex_deletion=False,
        )
    incident_faces = np.concatenate(
        [
            edge_face_ids[order[start : start + counts[group]]]
            for group, start in zip(non_manifold_groups, first[non_manifold_groups])
        ]
    )
    unsafe_regions = np.unique(region_ids[incident_faces])
    region_sizes = np.bincount(region_ids)
    all_regions = np.arange(len(region_sizes), dtype=np.int64)
    safe_regions = all_regions[~np.isin(all_regions, unsafe_regions)]
    # Tiny disconnected islands frequently collapse completely under VTK's
    # decimator.  Keeping them untouched preserves the exact component count.
    decimatable_regions = safe_regions[
        region_sizes[safe_regions] >= _MIN_DECIMATABLE_COMPONENT_FACES
    ]
    if not decimatable_regions.size:
        raise MeshError(
            "Упрощение невозможно без ухудшения non-manifold компонент"
        )
    requested_removed = reduction * len(faces)
    decimatable_faces = int(region_sizes[decimatable_regions].sum())
    safe_reduction = min(requested_removed / decimatable_faces, 0.95)
    if safe_reduction <= 0:
        raise MeshError("Недостаточно manifold-компонент для безопасного упрощения")

    decimatable_mask = np.isin(region_ids, decimatable_regions)
    untouched_ids = np.flatnonzero(~decimatable_mask)
    appender = vtkAppendPolyData()
    untouched = (
        connected.extract_cells(untouched_ids)
        .extract_surface(algorithm="dataset_surface")
        .triangulate()
    )
    appender.AddInputData(untouched)

    cells_by_region = np.argsort(region_ids, kind="stable")
    offsets = np.concatenate(([0], np.cumsum(region_sizes)))
    for region in decimatable_regions:
        cell_ids = cells_by_region[offsets[region] : offsets[region + 1]]
        component = (
            connected.extract_cells(cell_ids)
            .extract_surface(algorithm="dataset_surface")
            .triangulate()
        )
        selected = component
        attempted_reduction = safe_reduction
        for _attempt in range(6):
            candidate = component.decimate_pro(
                attempted_reduction,
                preserve_topology=True,
                splitting=False,
                boundary_vertex_deletion=False,
            )
            if (
                candidate.n_cells < component.n_cells
                and _is_closed_manifold(candidate)
            ):
                selected = candidate
                break
            attempted_reduction *= 0.5
        appender.AddInputData(selected)
    appender.Update()
    return pv.wrap(appender.GetOutput()).triangulate()


def _is_closed_manifold(poly) -> bool:
    faces = np.asarray(poly.faces, dtype=np.int64).reshape(-1, 4)[:, 1:]
    if not len(faces):
        return False
    edges = np.sort(
        np.vstack((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)])),
        axis=1,
    )
    _unique, counts = np.unique(edges, axis=0, return_counts=True)
    return bool(np.all(counts == 2))


def _repair_worker(
    output,
    vertices: np.ndarray,
    faces: np.ndarray,
    hole_size_mm: float,
    keep_largest: bool,
) -> None:
    try:
        import pyvista as pv

        vtk_faces = np.column_stack(
            (np.full(len(faces), 3, dtype=np.int64), faces)
        ).ravel()
        poly = pv.PolyData(vertices, vtk_faces).triangulate().clean()
        repaired = poly.fill_holes(hole_size_mm).triangulate().clean()
        if keep_largest and repaired.n_cells:
            repaired = (
                repaired.connectivity(extraction_mode="largest")
                .extract_surface(algorithm="dataset_surface")
                .triangulate()
            )
        result_faces = np.asarray(repaired.faces, dtype=np.int64).reshape(-1, 4)[:, 1:]
        output.send((True, np.asarray(repaired.points), result_faces, ""))
    except BaseException as exc:
        output.send((False, None, None, f"{type(exc).__name__}: {exc}"))
    finally:
        output.close()


def repair_mesh(
    mesh: Mesh,
    *,
    hole_size_mm: float,
    keep_largest_component: bool = False,
    timeout_seconds: float = 30.0,
) -> Mesh:
    if not np.isfinite(hole_size_mm) or hole_size_mm <= 0:
        raise MeshError("Максимальный размер отверстия должен быть положительным")
    before = mesh_metrics(mesh)
    context = mp.get_context("spawn")
    parent_output, child_output = context.Pipe(duplex=False)
    process = context.Process(
        target=_repair_worker,
        args=(
            child_output,
            mesh.vertices_lps_mm,
            mesh.faces,
            float(hole_size_mm),
            bool(keep_largest_component),
        ),
        daemon=True,
    )
    process.start()
    child_output.close()
    if not parent_output.poll(timeout_seconds):
        process.terminate()
        process.join(5)
        raise MeshError("Ремонт сетки превысил допустимое время")
    try:
        ok, vertices, faces, message = parent_output.recv()
    except (EOFError, OSError) as exc:
        process.join(5)
        raise MeshError("Процесс ремонта не вернул результат") from exc
    finally:
        parent_output.close()
    process.join(5)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise MeshError("Процесс ремонта не смог корректно завершиться")
    if process.exitcode != 0:
        raise MeshError("Нативный процесс ремонта сетки аварийно завершился")
    if not ok:
        raise MeshError(f"Ремонт сетки не выполнен: {message}")
    operation = f"repair(hole={hole_size_mm:g},largest={keep_largest_component})"
    repaired = Mesh(vertices, faces, mesh.segmentation_version, [*mesh.operations, operation])
    after = _ensure_usable(repaired)
    if after["boundary_edges"] > before["boundary_edges"]:
        raise MeshError("Repair увеличил число открытых граничных рёбер")
    if after["non_manifold_edges"] > before["non_manifold_edges"]:
        raise MeshError("Repair увеличил число non-manifold рёбер")
    if after["components"] > before["components"]:
        raise MeshError("Repair увеличил число связных компонент")
    repaired_boundaries = after["boundary_edges"] < before["boundary_edges"]
    repaired_non_manifold = after["non_manifold_edges"] < before["non_manifold_edges"]
    removed_components = (
        keep_largest_component
        and before["components"] > 1
        and after["components"] == 1
    )
    if not (repaired_boundaries or repaired_non_manifold or removed_components):
        if (
            before["boundary_edges"] == 0
            and before["non_manifold_edges"] == 0
            and (not keep_largest_component or before["components"] <= 1)
        ):
            raise MeshError("Исправление не требуется: выбранных дефектов не обнаружено")
        raise MeshError(
            "Заданные параметры repair не исправили обнаруженные дефекты сетки"
        )
    return repaired


def export_stl(mesh: Mesh, path: str | Path) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != ".stl":
        destination = destination.with_suffix(".stl")
    if not destination.parent.exists():
        raise MeshError("Папка для экспорта не существует")
    _ensure_usable(mesh)
    try:
        to_pyvista(mesh).save(destination, binary=True)
    except Exception as exc:
        raise MeshError("Не удалось сохранить STL") from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise MeshError("STL-файл не был создан")
    return destination


def _ensure_usable(mesh: Mesh) -> dict[str, object]:
    metrics = mesh_metrics(mesh)
    if metrics["vertices"] < 3 or metrics["triangles"] < 1:
        raise MeshError("Операция вернула пустую сетку")
    return metrics


def _ensure_topology_preserved(
    before: dict[str, object], result_metrics: dict[str, object]
) -> None:
    if result_metrics["boundary_edges"] != before["boundary_edges"]:
        raise MeshError("Операция изменила число открытых граничных рёбер")
    if result_metrics["components"] != before["components"]:
        raise MeshError("Операция изменила число связных компонент")
    if result_metrics["non_manifold_edges"] > before["non_manifold_edges"]:
        raise MeshError("Операция добавила non-manifold рёбра")
