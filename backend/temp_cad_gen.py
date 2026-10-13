# A build123d script to create a 2-inch diameter sphere.

from build123d import *

# Define the conversion from inches to millimeters, as build123d defaults to mm.
inch = 25.4

# Calculate the radius from the desired 2-inch diameter.
sphere_diameter = 2 * inch
sphere_radius = sphere_diameter / 2

# Create the sphere. The Sphere primitive is centered at (0,0,0) by default.
# The Sphere constructor takes radius as its primary argument.
result_part = Sphere(radius=sphere_radius)

# Export the final part to an STL file.
# The user requested the model to be unscaled, and since we worked in mm from the start,
# the exported STL will have the correct dimensions.
export_stl(result_part, 'output.stl')