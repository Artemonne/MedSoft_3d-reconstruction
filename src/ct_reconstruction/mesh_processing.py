"""Verified surface processing, with native hole filling isolated in a process."""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import numpy as np

from .errors import MeshError
from .models import Mesh
from .surface import from_pyvista, mesh_metrics, to_pyvista


def smooth_mesh(
    mesh: Mesh, *, iterations: int = 20, relaxation: float = 0.01
) -> Mesh:
    if iterations < 1 or not 0 < relaxation <= 1:
        raise MeshError("Некорректные параметры сглаживания")
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
    _ensure_usable(processed)
    return processed


def decimate_mesh(mesh: Mesh, *, reduction: float = 0.5) -> Mesh:
    if not 0 < reduction < 1:
        raise MeshError("Доля упрощения должна находиться между 0 и 1")
    poly = to_pyvista(mesh)
    result = poly.decimate_pro(
        reduction,
        preserve_topology=True,
        splitting=False,
        boundary_vertex_deletion=False,
    )
    processed = from_pyvista(
        result, source=mesh, operation=f"decimate({reduction:g})"
    )
    _ensure_usable(processed)
    if len(processed.faces) >= len(mesh.faces):
        raise MeshError("Упрощение не уменьшило число треугольников")
    return processed


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
    _ensure_usable(repaired)
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


def _ensure_usable(mesh: Mesh) -> None:
    metrics = mesh_metrics(mesh)
    if metrics["vertices"] < 3 or metrics["triangles"] < 1:
        raise MeshError("Операция вернула пустую сетку")
    if metrics["non_manifold_edges"]:
        raise MeshError("После операции появились non-manifold рёбра")

