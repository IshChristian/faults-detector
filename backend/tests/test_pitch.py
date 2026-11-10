import numpy as np
import pytest

from app.analysis.pitch import LANDMARKS, CalibrationError, fit_homography, project

PITCH = [(0, 0), (100, 0), (100, 64), (0, 64)]
IMG = [(0.1, 0.9), (0.9, 0.9), (0.7, 0.3), (0.3, 0.3)]


def test_homography_maps_clicked_points_to_pitch_points():
    H = fit_homography(IMG, PITCH)
    assert H.shape == (3, 3)
    assert np.allclose(project(H, np.array(IMG)), np.array(PITCH), atol=1e-6)


def test_landmarks_scale_with_pitch_size():
    assert LANDMARKS["halfway_far"](60, 40) == (30, 40)
    assert LANDMARKS["corner_near_left"](60, 40) == (0, 0)
    assert LANDMARKS["corner_near_right"](60, 40) == (60, 0)
    assert LANDMARKS["corner_far_right"](60, 40) == (60, 40)
    assert LANDMARKS["corner_far_left"](60, 40) == (0, 40)
    assert LANDMARKS["halfway_near"](60, 40) == (30, 0)
    assert LANDMARKS["centre_spot"](60, 40) == (30, 20)
    assert LANDMARKS["penalty_spot_left"](60, 40) == (11, 20)
    assert LANDMARKS["penalty_spot_right"](60, 40) == (49, 20)


@pytest.mark.parametrize("img,msg", [
    ([(0.1, 0.5), (0.5, 0.5), (0.9, 0.5), (0.5, 0.1)], "on one line"),
    ([(0.1, 0.9), (0.9, 0.9), (0.3, 0.3), (0.7, 0.3)], "cross over"),  # bow-tie
    ([(0.9, 0.9), (0.1, 0.9), (0.3, 0.3), (0.7, 0.3)], "cross over"),  # simple but mirrored
])
def test_collinear_or_bowtie_points_are_rejected(img, msg):
    with pytest.raises(CalibrationError, match=msg):
        fit_homography(img, PITCH)


def test_collinear_pitch_points_are_rejected():
    with pytest.raises(CalibrationError, match="on one line"):
        fit_homography(IMG, [(0, 0), (50, 0), (100, 0), (0, 64)])


def test_bowtie_pitch_points_are_rejected():
    with pytest.raises(CalibrationError, match="cross over"):
        fit_homography(IMG, [(0, 0), (100, 64), (100, 0), (0, 64)])


def test_points_outside_frame_are_rejected():
    with pytest.raises(CalibrationError, match="Image points must be inside the frame"):
        fit_homography([(0.1, 0.9), (1.2, 0.9), (0.7, 0.3), (0.3, 0.3)], PITCH)


def test_wrong_point_count_is_rejected():
    with pytest.raises(CalibrationError, match="Exactly 4 points are needed"):
        fit_homography(IMG[:3], PITCH[:3])


def test_check_order_is_count_then_frame_then_collinear_then_crossing():
    outside_and_collinear = [(0.1, 0.5), (0.5, 0.5), (1.5, 0.5), (0.5, 0.1)]
    with pytest.raises(CalibrationError, match="inside the frame"):
        fit_homography(outside_and_collinear, PITCH)


def test_project_marks_points_behind_camera_as_nan():
    H = np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1.0]])
    out = project(H, np.array([[1.0, 2.0]]))
    assert np.isnan(out).all()


def _pinhole(tilt_deg: float, cam=(50.0, -5.0, 3.5), fx=0.5, fy=0.5 * 16 / 9):
    """A 16:9 camera on a pole at halfway, 5 m behind the near touchline, looking across the pitch and tilted
    down by `tilt_deg`. Returns pitch (x, y) metres -> image-relative (x, y), y down."""
    t = np.radians(tilt_deg)
    c = np.array(cam)
    right, fwd, up = np.array([1.0, 0, 0]), np.array([0, np.cos(t), -np.sin(t)]), np.array([0, np.sin(t), np.cos(t)])

    def to_image(p):
        v = np.array([p[0], p[1], 0.0]) - c
        return (0.5 + fx * (v @ right) / (v @ fwd), 0.5 - fy * (v @ up) / (v @ fwd))

    horizon_y = 0.5 - fy * np.tan(t)
    return to_image, horizon_y


@pytest.mark.parametrize("tilt", [4, 8, 14])
def test_horizon_inside_the_frame_still_projects_the_pitch(tilt):
    # The image's top-left corner is sky, above the horizon: the solver must not assume w > 0 there.
    to_image, horizon_y = _pinhole(tilt)
    assert 0 < horizon_y < 0.5
    pitch = [(40, 12), (60, 12), (65, 50), (35, 50)]
    img = [to_image(p) for p in pitch]
    H = fit_homography(img, pitch)
    assert np.allclose(project(H, np.array([to_image((50, 32))])), [[50, 32]], atol=1e-6)
    assert np.allclose(project(H, np.array(img)), np.array(pitch), atol=1e-6)


def test_horizon_through_the_image_origin_does_not_crash():
    # True h33 == 0: the image origin maps to infinity. A solver that fixes h33 = 1 hits a singular system.
    H_true = np.array([[80.0, 10.0, 0.0], [0.0, -60.0, 60.0], [0.4, 1.2, 0.0]])
    img = [(0.2, 0.8), (0.8, 0.8), (0.7, 0.2), (0.3, 0.3)]
    pitch = [tuple(p) for p in project(H_true, np.array(img))]
    H = fit_homography(img, pitch)
    probe = np.array([[0.5, 0.5]])
    assert np.allclose(project(H, probe), project(H_true, probe), atol=1e-6)


def test_points_on_both_sides_of_the_horizon_are_rejected():
    # An exact fit exists, but some clicked points would sit behind the camera (w <= 0): metrics would be NaN.
    img = [(0.87, 0.07), (0.08, 0.93), (0.54, 0.1), (0.64, 0.14)]
    pitch = [(-263.636, -13.576), (15.094, 112.302), (-180.0, -21.333), (-246.154, -34.462)]
    with pytest.raises(CalibrationError, match="horizon"):
        fit_homography(img, pitch)
