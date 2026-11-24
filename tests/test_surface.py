from __future__ import annotations

import numpy as np
import pytest

from ct_reconstruction.errors import MeshError
from ct_reconstruction.models import Segmentation, VolumeGeometry
from ct_reconstruction.surface import marching_cubes_surface, mesh_metrics, to_pyvista


def geometry():
    return VolumeGeometry(
        (2.5, 0.7, 0.8), np.array([10.0, 20.0, 30.0]),
        np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
    )


def segmentation(mask):
    return Segmentation(np.asarray(mask, dtype=np.bool_), "threshold", {}, 1, 3)


def test_marching_cubes_builds_closed_anisotropic_surface():
    mask = np.zeros((3, 4, 5), dtype=np.bool_)
    mask[1, 1:3, 1:4] = True
    mesh = marching_cubes_surface(segmentation(mask), geometry())
    metrics = mesh_metrics(mesh)
    assert mesh.faces.shape[1] == 3
    assert metrics["triangles"] > 0
    assert metrics["boundary_edges"] == 0
    assert metrics["non_manifold_edges"] == 0
    assert metrics["bounds"] == pytest.approx((10.4, 12.8, 20.35, 21.75, 31.25, 33.75))
    poly = to_pyvista(mesh).compute_normals(cell_normals=True, point_normals=False)
    centers = poly.cell_centers().points
    normals = poly.cell_data["Normals"]
    assert normals[np.argmax(centers[:, 2]), 2] > 0
    assert normals[np.argmin(centers[:, 2]), 2] < 0


def test_full_mask_is_closed_by_padding():
    mesh = marching_cubes_surface(segmentation(np.ones((2, 2, 2), dtype=np.bool_)), geometry())
    assert mesh_metrics(mesh)["boundary_edges"] == 0


def test_oblique_geometry_transforms_vertices_and_preserves_outward_winding():
    mask = np.zeros((3, 4, 5), dtype=np.bool_)
    mask[1, 1:3, 1:4] = True
    base_geometry = VolumeGeometry(
        (2.5, 0.7, 0.8), np.zeros(3),
        np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
    )
    rotated_geometry = VolumeGeometry(
        (2.5, 0.7, 0.8), np.array([10.0, 20.0, 30.0]),
        np.array([0.0, 1.0, 0]), np.array([-1.0, 0, 0]), np.array([0, 0, 1.0])
    )
    base = marching_cubes_surface(segmentation(mask), base_geometry)
    rotated = marching_cubes_surface(segmentation(mask), rotated_geometry)
    expected = np.column_stack(
        (-base.vertices_lps_mm[:, 1], base.vertices_lps_mm[:, 0], base.vertices_lps_mm[:, 2])
    ) + np.array([10.0, 20.0, 30.0])
    assert rotated.vertices_lps_mm == pytest.approx(expected, abs=1e-12)
    poly = to_pyvista(rotated).compute_normals(cell_normals=True, point_normals=False)
    centers = poly.cell_centers().points
    normals = poly.cell_data["Normals"]
    object_center = rotated.vertices_lps_mm.mean(axis=0)
    assert np.all(np.einsum("ij,ij->i", centers - object_center, normals) > 0)


def test_empty_mask_is_rejected():
    with pytest.raises(MeshError, match="пуста"):
        marching_cubes_surface(segmentation(np.zeros((2, 2, 2))), geometry())
