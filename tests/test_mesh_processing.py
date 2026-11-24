from __future__ import annotations

import numpy as np
import pyvista as pv
import pytest

from ct_reconstruction.mesh_processing import (
    decimate_mesh,
    export_stl,
    repair_mesh,
    smooth_mesh,
)
from ct_reconstruction.errors import MeshError
from ct_reconstruction.models import Mesh
from ct_reconstruction.surface import from_pyvista, mesh_metrics


def model_from_poly(poly) -> Mesh:
    seed = Mesh(np.empty((0, 3)), np.empty((0, 3), dtype=np.int64), 1)
    return from_pyvista(poly.triangulate(), source=seed, operation="fixture")


def test_smoothing_and_decimation_change_real_mesh():
    original = model_from_poly(pv.Sphere(radius=10, theta_resolution=40, phi_resolution=40))
    smoothed = smooth_mesh(original, iterations=10, relaxation=0.05)
    decimated = decimate_mesh(smoothed, reduction=0.5)
    assert not np.allclose(smoothed.vertices_lps_mm, original.vertices_lps_mm)
    assert len(decimated.faces) < len(smoothed.faces)
    assert mesh_metrics(decimated)["non_manifold_edges"] == 0


def test_repair_fills_a_small_hole_and_can_remove_fragment():
    sphere = pv.Sphere(radius=5, theta_resolution=30, phi_resolution=30).triangulate()
    centers = sphere.cell_centers().points
    damaged = sphere.remove_cells(np.flatnonzero(centers[:, 2] > 4.8)).extract_surface(
        algorithm="dataset_surface"
    )
    detached = pv.Sphere(radius=0.3, center=(20, 0, 0)).triangulate()
    combined = damaged + detached
    source = model_from_poly(combined)
    assert mesh_metrics(source)["boundary_edges"] > 0
    assert mesh_metrics(source)["components"] == 2
    repaired = repair_mesh(
        source, hole_size_mm=2.0, keep_largest_component=True, timeout_seconds=30
    )
    metrics = mesh_metrics(repaired)
    assert metrics["boundary_edges"] == 0
    assert metrics["non_manifold_edges"] == 0
    assert metrics["components"] == 1


def test_stl_round_trip_uses_active_mesh_coordinates(tmp_path):
    mesh = model_from_poly(pv.Box(bounds=(1, 11, 2, 7, 3, 9)).triangulate())
    destination = export_stl(mesh, tmp_path / "model")
    loaded = pv.read(destination).triangulate()
    assert destination.suffix == ".stl"
    assert loaded.n_cells == len(mesh.faces)
    assert loaded.bounds == pytest.approx(mesh_metrics(mesh)["bounds"], abs=0.001, rel=1e-5)


def test_repair_timeout_preserves_parent_process():
    mesh = model_from_poly(pv.Sphere(radius=5).triangulate())
    with pytest.raises(MeshError, match="время"):
        repair_mesh(mesh, hole_size_mm=1, timeout_seconds=0.0001)

