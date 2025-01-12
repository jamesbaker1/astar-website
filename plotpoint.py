from PIL import Image, ImageDraw

def plot_point_on_image(image_path, x_pct, y_pct, point_radius=5, point_color="red"):
    """
    Plots a point on a JPG image at the (x_pct, y_pct) location, where x_pct and y_pct 
    are percentages in the range [0, 1].

    :param image_path: Path to the input JPG image.
    :param x_pct: Float representing how far along the width the point should be (0 to 1).
    :param y_pct: Float representing how far along the height the point should be (0 to 1).
    :param point_radius: Radius of the circle (point) to draw.
    :param point_color: Color of the point (any Pillow color format).
    :return: A Pillow Image object with the point drawn on it.
    """
    # 1. Open the image
    img = Image.open(image_path)
    
    # 2. Get image dimensions
    width, height = img.size

    # 3. Convert percentages to absolute pixel coordinates
    x_coord = int(x_pct * width)
    y_coord = int(y_pct * height)

    # 4. Draw a small circle at (x_coord, y_coord)
    draw = ImageDraw.Draw(img)
    left_upper = (x_coord - point_radius, y_coord - point_radius)
    right_lower = (x_coord + point_radius, y_coord + point_radius)
    draw.ellipse([left_upper, right_lower], fill=point_color, outline=point_color)

    # (Optional) Show the image with the plotted point
    # img.show()

    # (Optional) Save the modified image
    # img.save("output.jpg")

    # Return the modified image object so it can be used further
    return img

# Example usage
if __name__ == "__main__":
    # Example: 50% across the width and 50% down the height (center of the image).
    result_image = plot_point_on_image(
        image_path="frame_1735930648.jpg",
        x_pct=.576,
        y_pct=0.5,
        point_radius=5,
        point_color="red"
    )
    
    # Show or save the result as needed
    result_image.show()
    # result_image.save("output_with_point.jpg")
