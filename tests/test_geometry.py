import numpy as np
import pytest

from vigia.geometry import View, direction, horizon_dip, local_en, on_vent_plane, sight

KP = (19.492709, -155.385281)
NORTH_VENT = (19.40496, -155.29022)
SIZE = (3840, 2160)


def view(yaw=180.0, pitch=0.0, roll=0.0, focal=1000.0, cx=1920.0, cy=1080.0):
    return View(np.atleast_1d(np.asarray(yaw, dtype=float)), np.atleast_1d(np.asarray(pitch, dtype=float)),
                np.atleast_1d(np.asarray(roll, dtype=float)), np.atleast_1d(np.asarray(focal, dtype=float)), cx, cy)


def at(azimuth, elevation):
    """One sample's directions (1, P, 3) for lists of azimuths and elevations."""
    return direction(np.asarray(azimuth, dtype=float), np.asarray(elevation, dtype=float))[None]


# --- positions


def test_kpcam_is_13948_m_from_the_north_vent_at_bearing_134_4():
    east, north = local_en(*NORTH_VENT, *KP)

    assert np.hypot(east, north) == pytest.approx(13948, abs=2)
    assert np.degrees(np.arctan2(east, north)) == pytest.approx(134.4, abs=0.05)


def test_curvature_and_refraction_lower_a_point_14_km_away_by_13_m():
    assert sight(13948.0, 0.0, 0.0)[2] == pytest.approx(-13.28, abs=0.01)
    assert sight(13948.0, 0.0, 0.0, k=0.0)[2] == pytest.approx(-15.27, abs=0.01)


def test_the_sea_horizon_from_2034_m_dips_1_35_degrees():
    assert horizon_dip(2034.0) == pytest.approx(1.3504, abs=1e-4)
    assert horizon_dip(2034.0, k=0.0) == pytest.approx(1.4478, abs=1e-4)


# --- projection


def test_the_optical_axis_lands_on_the_principal_point():
    pixels = view(yaw=134.4, pitch=-3.9).project(at([134.4], [-3.9]))

    assert pixels[0, 0] == pytest.approx([1920, 1080])


def test_a_level_point_10_degrees_right_lands_f_tan_10_right_of_centre():
    pixels = view(yaw=180).project(at([190], [0]))

    assert pixels[0, 0] == pytest.approx([1920 + 1000 * np.tan(np.radians(10)), 1080])


def test_a_point_above_the_axis_lands_above_the_centre():
    assert view(pitch=5).project(at([180], [10]))[0, 0, 1] == pytest.approx(1080 - 1000 * np.tan(np.radians(5)))


def test_positive_roll_raises_the_right_side_of_a_level_line():
    left, right = view(roll=2).project(at([170, 190], [0, 0]))[0]

    assert right[1] < 1080 < left[1]


def test_points_behind_the_camera_do_not_project():
    assert np.isnan(view(yaw=0).project(at([180], [0]))).all()


def test_ray_inverts_project():
    camera = view(yaw=146.6, pitch=3.8, roll=0.7, focal=3050)
    pixels = camera.project(at([130, 150, 170], [-4, 10, 21]))

    azimuth, elevation = camera.ray(pixels)

    assert azimuth[0] == pytest.approx([130, 150, 170])
    assert elevation[0] == pytest.approx([-4, 10, 21])


def test_barrel_distortion_pulls_a_point_towards_the_centre_by_k1_r_squared():
    camera = View(np.array([180.0]), np.array([0.0]), np.array([0.0]), np.array([1000.0]), 1920, 1080, k1=-0.2)
    r = np.tan(np.radians(30))

    pixel = camera.project(at([210], [0]))[0, 0]

    assert pixel == pytest.approx([1920 + 1000 * r * (1 - 0.2 * r ** 2), 1080])


def test_ray_undoes_the_distortion_out_to_the_corners():
    camera = View(np.array([145.5]), np.array([3.0]), np.array([-0.1]), np.array([3485.0]), 1920, 1080, k1=-0.27)
    pixels = np.array([[[0.0, 0.0], [3839.0, 2159.0], [66.8, 562.1], [1920.0, 1080.0]]])

    assert camera.project(direction(*camera.ray(pixels))) == pytest.approx(pixels, abs=1e-6)


# --- heights on the vent plane


def vent_1km_north_100m_below():
    return sight(0.0, 1000.0, -100.0)[None]  # (1, 3)


def test_a_point_above_the_vent_rises_to_its_true_height():
    camera = view(yaw=0, focal=1500)
    target = sight(0.0, 1000.0, 100.0)[None, None]  # 200 m above the vent: 100 m above the camera

    reach, across, rise = on_vent_plane(camera, camera.project(target), vent_1km_north_100m_below())

    assert (reach[0, 0], across[0, 0], rise[0, 0]) == pytest.approx((1000, 0, 100), abs=1e-6)


def test_a_point_beside_the_vent_is_measured_in_the_plane_square_to_the_line_of_sight():
    camera = view(yaw=0, focal=1500)
    target = sight(100.0, 1000.0, 50.0)[None, None]

    reach, across, rise = on_vent_plane(camera, camera.project(target), vent_1km_north_100m_below())

    assert (reach[0, 0], across[0, 0], rise[0, 0]) == pytest.approx((np.hypot(100, 1000), 100, 50), abs=1e-6)


def test_a_point_beyond_the_plane_is_measured_where_along_puts_it():
    camera = view(yaw=0, focal=1500)
    target = sight(0.0, 1050.0, 100.0)[None, None]

    reach, _, rise = on_vent_plane(camera, camera.project(target), vent_1km_north_100m_below(), along=50.0)

    assert (reach[0, 0], rise[0, 0]) == pytest.approx((1050, 100), abs=1e-6)


def test_a_pixel_looking_far_from_the_vent_is_refused():
    camera = view(yaw=90, focal=1500)

    with pytest.raises(ValueError, match="80 degrees"):
        on_vent_plane(camera, np.array([[[1920.0, 1080.0]]]), vent_1km_north_100m_below())
