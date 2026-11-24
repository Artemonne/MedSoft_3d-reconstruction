"""Marching Cubes and mesh conversion helpers."""

from __future__ import annotations

import numpy as np
from skimage.measure import marching_cubes

from .errors import MeshError
from .models import Mesh, Segmentation, VolumeGeometry


def marching_cubes_surface(
    segmentation: Segmentation, geometry: VolumeGeometry
) -> Mesh:
    mask = segmentation.mask
    if not mask.any():
        raise MeshError("Маска пуста; поверхность построить нельзя")
    padded = np.pad(mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    dz, dr, dc = geometry.spacing_zyx_mm
    try:
        vertices_zyx, faces, _normals, _values = marching_cubes(
            padded,
            level=0.5,
            spacing=(dz, dr, dc),
            method="lewiner",
            allow_degenerate=False,
        )
    except (RuntimeError, ValueError) as exc:
        raise MeshError("Marching Cubes не смог построить поверхность") from exc

    vertices_zyx -= np.asarray((dz, dr, dc), dtype=np.float64)
    vertices_lps = (
        geometry.origin_lps_mm
        + vertices_zyx[:, 0, None] * geometry.slice_direction_lps
        + vertices_zyx[:, 1, None] * geometry.row_direction_lps
        + vertices_zyx[:, 2, None] * geometry.column_direction_lps
    )
    mesh = Mesh(
        vertices_lps_mm=np.asarray(vertices_lps, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        segmentation_version=segmentation.version,
        operations=["marching_cubes"],
    )
    if len(mesh.faces) == 0:
        raise MeshError("Marching Cubes вернул пустую сетку")
    return mesh


def to_pyvista(mesh: Mesh):
    import pyvista as pv

    vtk_faces = np.column_stack(
        (np.full(len(mesh.faces), 3, dtype=np.int64), mesh.faces)
    ).ravel()
    return pv.PolyData(mesh.vertices_lps_mm, vtk_faces)


def from_pyvista(polydata, *, source: Mesh, operation: str) -> Mesh:
    triangulated = polydata.triangulate()
    faces = np.asarray(triangulated.faces).reshape(-1, 4)
    if len(faces) and not np.all(faces[:, 0] == 3):
        raise MeshError("Операция вернула нетреугольную сетку")
    return Mesh(
        np.asarray(triangulated.points, dtype=np.float64),
        np.asarray(faces[:, 1:], dtype=np.int64),
        source.segmentation_version,
        [*source.operations, operation],
    )


def mesh_metrics(mesh: Mesh) -> dict[str, object]:
    poly = to_pyvista(mesh)
    boundary = poly.extract_feature_edges(
        boundary_edges=True,
        feature_edges=False,
        manifold_edges=False,
        non_manifold_edges=False,
    )
    non_manifold = poly.extract_feature_edges(
        boundary_edges=False,
        feature_edges=False,
        manifold_edges=False,
        non_manifold_edges=True,
    )
    regions = poly.connectivity()
    region_ids = np.asarray(regions.cell_data.get("RegionId", []))
    return {
        "vertices": int(poly.n_points),
        "triangles": int(poly.n_cells),
        "boundary_edges": int(boundary.n_cells),
        "non_manifold_edges": int(non_manifold.n_cells),
        "components": int(region_ids.max() + 1) if region_ids.size else 0,
        "bounds": tuple(float(value) for value in poly.bounds),
        "volume_mm3": float(poly.volume) if boundary.n_cells == 0 else None,
    }

