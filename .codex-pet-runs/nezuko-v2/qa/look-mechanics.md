# Nezuko look mechanics

Nezuko is a compact humanoid pixel-art pet. Her feet and lower torso remain registered to the same baseline while her pink eyes lead the gaze, followed by a restrained head and neck turn. The bamboo muzzle stays rigidly attached across the mouth and turns with the head; it never floats or changes size. Her long hair, orange tips, haori, kimono, ribbon, and body proportions remain unchanged, with only subtle side-dependent occlusion and one-step follow-through.

Motion budget: every 22.5-degree step changes the pupils/eye surfaces, eyelids, head yaw or pitch, visible cheek width, bamboo-muzzle perspective, and upper-hair overlap by a small even amount. No whole-sprite rotation, broad facial warp, scale change, baseline shift, or prop teleport is allowed.

- 000 up: eyes clearly high, eyelids open upward, chin and bamboo muzzle lift slightly; forehead and upper face read more strongly while the feet stay fixed.
- 090 screen-right: pupils and nose/face center shift toward screen-right, head turns right, the screen-right cheek and hair side become more visible, and the screen-left facial side becomes slightly occluded; bamboo muzzle follows the same yaw.
- 180 down: eyes clearly low with upper eyelids lowered, chin and bamboo muzzle dip slightly, and upper hair overlaps the face a little more; the body remains anchored.
- 270 screen-left: pupils and nose/face center shift toward screen-left, head turns left, the screen-left cheek and hair side become more visible, and the screen-right facial side becomes slightly occluded; bamboo muzzle follows the same yaw.

Diagonals interpolate these four families evenly. Pink eye construction, facial proportions, ribbon side, hair silhouette, kimono folds, haori, and bamboo attachment must remain identity-locked. The final 337.5 pose is exactly one small step before 000, and 157.5 is exactly one small step before 180.
