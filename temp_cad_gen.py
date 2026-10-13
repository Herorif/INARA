from build123d import *
import numpy as np

# --- Gear Parameters ---
num_teeth = 20
pitch_radius = 40.0  # The effective radius of the gear
gear_thickness = 15.0
bore_diameter = 12.0
keyway_width = 4.0
keyway_height = 3.0  # Depth into the hub

# Derived Parameters
# Module is a measure of gear tooth size (Diameter / Teeth)
module = (pitch_radius * 2) / num_teeth 
addendum = 1.0 * module  # Height of tooth above pitch circle
dedendum = 1.25 * module # Depth of tooth below pitch circle
tooth_height = addendum + dedendum
root_radius = pitch_radius - dedendum
tip_radius = pitch_radius + addendum

# Tooth profile widths (Approximation for generic look)
tooth_base_width = (np.pi * pitch_radius / num_teeth) * 0.55
tooth_tip_width = tooth_base_width * 0.4

# --- Modeling ---
with BuildPart() as p:
    
    # 1. Create the Gear Profile Sketch
    with BuildSketch() as profile_sk:
        # The main root circle (hub body)
        Circle(radius=root_radius)
        
        # Create the teeth
        with PolarLocations(radius=root_radius, count=num_teeth):
            # We define a polygon for a single tooth.
            # Local X is radial (pointing out), Local Y is tangential.
            # We start slightly inside the root circle (x=-1) to ensure the 
            # tooth fuses perfectly with the circle.
            Polygon([
                (-1.0, -tooth_base_width / 2),  # Bottom Left
                (tooth_height, -tooth_tip_width / 2), # Top Left
                (tooth_height, tooth_tip_width / 2),  # Top Right
                (-1.0, tooth_base_width / 2)    # Bottom Right
            ])
            
    # 2. Extrude the sketch to create the solid gear
    extrude(amount=gear_thickness)

    # 3. Cut the Central Bore and Keyway
    with BuildSketch(faces().sort_by(Axis.Z)[-1]) as bore_sk:
        # Center hole
        Circle(radius=bore_diameter / 2)
        
        # Keyway (Rectangle fused to the top of the bore)
        with Locations((0, bore_diameter / 2)):
            # Centered rectangle placed at the edge of the bore
            Rectangle(width=keyway_width, height=keyway_height * 2)
            
    extrude(amount=-gear_thickness, mode=Mode.SUBTRACT)

    # 4. Finishing Touches (Chamfers)
    # We select the circular edges of the bore to chamfer.
    # Logic: Filter edges by Circle type, sort by radius (bore is smallest), 
    # then pick the ones matching the bore radius roughly.
    try:
        bore_edges = (
            p.edges()
            .filter_by(GeomType.CIRCLE)
            .filter_by(lambda e: abs(e.radius - bore_diameter/2) < 0.1)
        )
        chamfer(bore_edges, length=0.8)
    except Exception:
        # Fallback if selection fails, just skip chamfer
        pass

# --- Output ---
result_part = p.part
export_stl(result_part, 'output.stl')

print(f"Gear generated with {num_teeth} teeth.")
print("Saved to 'output.stl'.")