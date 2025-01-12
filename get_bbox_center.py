def get_bbox_center(bbox):
    """
    Given [ymin, xmin, ymax, xmax] in the range [0..1000],
    compute the center [x_center, y_center] in normalized coordinates.
    """
    ymin, xmin, ymax, xmax = bbox

    # Normalize each coordinate
    ymin_norm = ymin / 1000.0
    xmin_norm = xmin / 1000.0
    ymax_norm = ymax / 1000.0
    xmax_norm = xmax / 1000.0

    # Compute center in normalized coordinates
    x_center = (xmin_norm + xmax_norm) / 2.0
    y_center = (ymin_norm + ymax_norm) / 2.0

    return [x_center, y_center]

print(get_bbox_center([391, 389, 736, 611]))

