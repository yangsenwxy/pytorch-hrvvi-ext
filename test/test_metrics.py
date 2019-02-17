import numpy as np

from hutil.train.metrics import mAP, BoundingBox, BoundingBoxFormat


def test_mAP():
    detections = [
        (1, 0, [5, 67, 31, 48], .88),
        (1, 0, [119, 111, 40, 67], .70),
        (1, 0, [124, 9, 49, 67], .80),
        (2, 0, [64, 111, 64, 58], .71),
        (2, 0, [26, 140, 60, 47], .54),
        (2, 0, [19, 18, 43, 35], .74),
        (3, 0, [109, 15, 77, 39], .18),
        (3, 0, [86, 63, 46, 45], .67),
        (3, 0, [160, 62, 36, 53], .38),
        (3, 0, [105, 131, 47, 47], .91),
        (3, 0, [18, 148, 40, 44], .44),
        (4, 0, [83, 28, 28, 26], .35),
        (4, 0, [28, 68, 42, 67], .78),
        (4, 0, [87, 89, 25, 39], .45),
        (4, 0, [10, 155, 60, 26], .14),
        (5, 0, [50, 38, 28, 46], .62),
        (5, 0, [95, 11, 53, 28], .44),
        (5, 0, [29, 131, 72, 29], .95),
        (5, 0, [29, 163, 72, 29], .23),
        (6, 0, [43, 48, 74, 38], .45),
        (6, 0, [17, 155, 29, 35], .84),
        (6, 0, [95, 110, 25, 42], .43),
        (7, 0, [16, 20, 101, 88], .48),
        (7, 0, [33, 116, 37, 49], .95),
    ]
    detections = [BoundingBox(
        image_name=d[0],
        class_id=d[1],
        box=d[2],
        confidence=d[3],
        box_format=BoundingBoxFormat.LTWH,
    ) for d in detections]

    ground_truths = [
        (1, 0, [25, 16, 38, 56]),
        (1, 0, [129, 123, 41, 62]),
        (2, 0, [123, 11, 43, 55]),
        (2, 0, [38, 132, 59, 45]),
        (3, 0, [16, 14, 35, 48]),
        (3, 0, [123, 30, 49, 44]),
        (3, 0, [99, 139, 47, 47]),
        (4, 0, [53, 42, 40, 52]),
        (4, 0, [154, 43, 31, 34]),
        (5, 0, [59, 31, 44, 51]),
        (5, 0, [48, 128, 34, 52]),
        (6, 0, [36, 89, 52, 76]),
        (6, 0, [62, 58, 44, 67]),
        (7, 0, [28, 31, 55, 63]),
        (7, 0, [58, 67, 50, 58]),
    ]
    ground_truths = [BoundingBox(
        image_name=d[0],
        class_id=d[1],
        box=d[2],
        box_format=BoundingBoxFormat.LTWH,
    ) for d in ground_truths]
    np.testing.assert_allclose(
        mAP(detections, ground_truths, iou_threshold=0.295), 0.2456867)
