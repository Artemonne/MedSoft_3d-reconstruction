from __future__ import annotations

import struct

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
    original_metrics = mesh_metrics(original)
    smoothed_metrics = mesh_metrics(smoothed)
    decimated_metrics = mesh_metrics(decimated)
    assert not np.allclose(smoothed.vertices_lps_mm, original.vertices_lps_mm)
    assert smoothed_metrics["boundary_edges"] == 0
    assert smoothed_metrics["non_manifold_edges"] == 0
    assert abs(smoothed_metrics["volume_mm3"] / original_metrics["volume_mm3"] - 1) <= 0.05
    actual_reduction = 1 - len(decimated.faces) / len(smoothed.faces)
    assert actual_reduction == pytest.approx(0.5, abs=0.05)
    assert decimated_metrics["boundary_edges"] == 0
    assert decimated_metrics["non_manifold_edges"] == 0
    assert abs(decimated_metrics["volume_mm3"] / smoothed_metrics["volume_mm3"] - 1) <= 0.05

    for source, target in ((original, smoothed), (smoothed, decimated)):
        source_poly = pv.PolyData(source.vertices_lps_mm)
        target_poly = pv.PolyData(target.vertices_lps_mm)
        distance_a = np.abs(
            source_poly.compute_implicit_distance(
                pv.PolyData(target.vertices_lps_mm, np.column_stack(
                    (np.full(len(target.faces), 3), target.faces)
                ).ravel())
            ).point_data["implicit_distance"]
        )
        distance_b = np.abs(
            target_poly.compute_implicit_distance(
                pv.PolyData(source.vertices_lps_mm, np.column_stack(
                    (np.full(len(source.faces), 3), source.faces)
                ).ravel())
            ).point_data["implicit_distance"]
        )
        assert max(float(distance_a.max()), float(distance_b.max())) <= 0.5


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


def test_repair_rejects_noop_when_hole_is_larger_than_limit():
    sphere = pv.Sphere(radius=5, theta_resolution=30, phi_resolution=30).triangulate()
    centers = sphere.cell_centers().points
    damaged = sphere.remove_cells(np.flatnonzero(centers[:, 2] > 4.5)).extract_surface(
        algorithm="dataset_surface"
    )
    source = model_from_poly(damaged)
    assert mesh_metrics(source)["boundary_edges"] > 0
    with pytest.raises(MeshError, match="не исправили"):
        repair_mesh(source, hole_size_mm=0.1, timeout_seconds=30)


def test_repair_does_not_modify_intact_mesh_silently():
    source = model_from_poly(pv.Sphere(radius=5).triangulate())
    with pytest.raises(MeshError, match="не требуется"):
        repair_mesh(source, hole_size_mm=2.0, timeout_seconds=30)


def test_stl_round_trip_uses_active_mesh_coordinates(tmp_path):
    mesh = model_from_poly(pv.Box(bounds=(1, 11, 2, 7, 3, 9)).triangulate())
    destination = export_stl(mesh, tmp_path / "model")
    loaded = pv.read(destination).triangulate()
    assert destination.suffix == ".stl"
    assert loaded.n_cells == len(mesh.faces)
    assert loaded.bounds == pytest.approx(mesh_metrics(mesh)["bounds"], abs=0.001, rel=1e-5)

    # Parse the binary STL independently of VTK/PyVista as a format check.
    raw = destination.read_bytes()
    triangle_count = struct.unpack_from("<I", raw, 80)[0]
    assert len(raw) == 84 + triangle_count * 50
    records = np.frombuffer(
        raw,
        dtype=np.dtype(
            [("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")]
        ),
        offset=84,
        count=triangle_count,
    )
    independent_points = records["vertices"].reshape(-1, 3)
    independent_bounds = tuple(
        value
        for axis in range(3)
        for value in (independent_points[:, axis].min(), independent_points[:, axis].max())
    )
    assert triangle_count == len(mesh.faces)
    assert independent_bounds == pytest.approx(mesh_metrics(mesh)["bounds"], abs=0.001, rel=1e-5)


def test_repair_timeout_preserves_parent_process():
    mesh = model_from_poly(pv.Sphere(radius=5).triangulate())
    with pytest.raises(MeshError, match="время"):
        repair_mesh(mesh, hole_size_mm=1, timeout_seconds=0.0001)
