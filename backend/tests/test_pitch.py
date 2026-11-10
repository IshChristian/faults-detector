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
