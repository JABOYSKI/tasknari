"""
Hyperdemon-Style Movement Demo
First-person 3D movement on a flat landscape with full momentum-based physics.

Controls:
  WASD        - Move (view-relative)
  Space       - Jump / Dash / Slide / Stomp (context-sensitive)
  Mouse       - Look around
  ESC         - Quit
  F1          - Toggle HUD info
  TAB         - Reset position

Movement States:
  Ground -> Jump -> Dash/Stomp -> Slide -> Bunny Hop -> ...
  See in-game HUD for current state and speed.

Requirements: pip install pygame PyOpenGL
"""

import sys
import math
import time
import struct
import array
import random

try:
    import pygame
    from pygame.locals import *
except ImportError:
    print("pygame not found. Install with: pip install pygame")
    sys.exit(1)

try:
    from OpenGL.GL import *
    from OpenGL.GLU import *
except ImportError:
    print("PyOpenGL not found. Install with: pip install PyOpenGL")
    sys.exit(1)


# =============================================================================
# Physics Constants (Quake-like, tuned for Hyperdemon feel)
# =============================================================================
GAME_SPEED = 1.75  # global time scale multiplier
GRAVITY = 749.0
GROUND_ACCEL = 20.0
GROUND_MAX_SPEED = 638.0
GROUND_FRICTION = 6.0
AIR_ACCEL = 24.0
AIR_MAX_SPEED = 80.0  # wishdir clamp for air strafing
JUMP_VELOCITY = 401.0
DASH_IMPULSE = 11372.0       # initial burst — the "fast" stage
DASH_DRAG = 4.0             # lower drag = longer tail-end glide
FAST_DASH_IMPULSE = 14164.0
SLIDE_DASH_IMPULSE = 6584.0
STOMP_VELOCITY = -2394.0
SLIDE_FRICTION = 1.5
SLIDE_MIN_SPEED = 50.0
BUNNY_HOP_BONUS = 1.05  # fallback speed multiplier (non-slide jumps)
MOUSE_SENSITIVITY = 0.15
PLAYER_HEIGHT = 50.0
PLAYER_CROUCH_HEIGHT = 25.0  # during slide
FAKE_JUMP_WINDOW = 0.1  # seconds after landing to input fake jump
DASH_STEER_RATE = 2.0  # how much you can steer mid-dash
DASH_DURATION = 0.45  # seconds (longer tail end)
FAST_DASH_DURATION = 0.2
SLIDE_DASH_DURATION = 0.7
SLIDE_MAX_DURATION = 1.5
DASH_COOLDOWN = 2.0  # seconds before dash is available again
BHOP_WINDOW = 0.4           # seconds after slide ends to press space for bhop
BHOP_PERFECT_WINDOW = 0.15  # press within this for max boost
BHOP_SPEED_BOOST = 1.375    # max speed multiplier on perfect bhop
BHOP_BASE_BOOST = 1.12      # minimum boost if within the window at all
DASH_DOUBLETAP_MIN = 0.1   # minimum gap between space presses to dash (ignore accidental)
DASH_DOUBLETAP_MAX = 0.5   # maximum gap — too slow = no dash

# Enemies
SKULL_COUNT = 8
SKULL_SPEED = 649.0
SKULL_RADIUS = 40.0  # collision/body radius
SKULL_WEAKSPOT_RADIUS = 16.0  # weak spot sized to match shotgun spread
SKULL_HP = 40
SKULL_SPAWN_RANGE = 2000.0
SKULL_MIN_DIST = 300.0  # minimum spawn distance from player
SKULL_PELLET_DAMAGE = 8  # per pellet hit on body
SKULL_WEAKSPOT_MULTIPLIER = 3  # damage multiplier on weak spot
SKULL_MAX = 30  # cap on total skulls

# Spawners (diamond structures)
SPAWNER_COUNT = 4  # initial spawners
SPAWNER_HP = 800
SPAWNER_REGEN = 80.0  # HP regenerated per second
SPAWNER_RADIUS = 244.0  # collision radius
SPAWNER_SPAWN_INTERVAL = 15.0  # seconds between skull spawns
SPAWNER_SPAWN_RANGE = 1500.0  # how far from player spawners appear
SPAWNER_MIN_DIST = 400.0  # minimum spawn distance from player
SPAWNER_NEW_INTERVAL = 30.0  # seconds between new spawner appearances
SPAWNER_MAX = 8  # max active spawners
SPAWNER_PELLET_DAMAGE = 6  # damage per pellet hit
SKULL_KILL_RADIUS = 30.0  # skull touches player = death
SKULL_WARN_RADIUS = 500.0  # red hologram overlay starts at this distance

# Ammonites (flat floating spiral enemies)
AMMONITE_COUNT = 3  # initial count
AMMONITE_HP = 120
AMMONITE_RADIUS = 180.0  # collision radius
AMMONITE_SPEED = 400.0
AMMONITE_ACCEL = 500.0
AMMONITE_DRAG = 2.5
AMMONITE_AGGRO_RANGE = 600.0  # only chases when player is this close
AMMONITE_HOVER_HEIGHT = 80.0
AMMONITE_PELLET_DAMAGE = 10
AMMONITE_CORPSE_RADIUS = AMMONITE_RADIUS  # touch radius matches visual size
AMMONITE_CORPSE_REVIVE = 6.0  # seconds before corpse revives
AMMONITE_BOOST_FORWARD = 900.0  # forward boost on corpse pickup (like a dash)
AMMONITE_BOOST_UP = 900.0  # upward boost - equal to forward for 45° launch
AMMONITE_SPAWN_RANGE = 1800.0
AMMONITE_MIN_DIST = 500.0
AMMONITE_MAX = 6
AMMONITE_KILL_RADIUS = AMMONITE_RADIUS  # touches player = death

# Player
PLAYER_MAX_HP = 100

# Shotgun
SHOTGUN_COOLDOWN = 0.75
SHOTGUN_PELLET_COUNT = 118
SHOTGUN_SPREAD = 15.0  # degrees
SHOTGUN_PELLET_SPEED = 1995.0
SHOTGUN_PELLET_LIFETIME = 1.2  # seconds
SHOTGUN_KNOCKBACK = 831.0  # thrust applied to player opposite to firing direction

# Diagonal speed factor (sqrt(2)/2 normalized but slightly boosted)
DIAGONAL_BONUS = 1.05

# =============================================================================
# Movement State Machine
# =============================================================================
STATE_GROUND = "GROUND"
STATE_AIRBORNE = "AIRBORNE"
STATE_DASHING = "DASHING"
STATE_SLIDING = "SLIDING"
STATE_STOMPING = "STOMPING"
STATE_DODGE = "DODGE"


class Player:
    def __init__(self):
        self.pos = [0.0, PLAYER_HEIGHT, 0.0]  # x, y (up), z
        self.vel = [0.0, 0.0, 0.0]
        self.yaw = 0.0  # horizontal look (degrees)
        self.pitch = 0.0  # vertical look (degrees)
        self.state = STATE_GROUND
        self.current_height = PLAYER_HEIGHT

        # Dash state
        self.dash_timer = 0.0
        self.dash_duration = 0.0
        self.dash_dir = [0.0, 0.0, 0.0]
        self.dash_type = "normal"  # normal, fast, slide
        self.dash_can_upgrade = False  # can this dash become fast/slide
        self.has_dashed = False  # one dash per airborne

        # Slide state
        self.slide_timer = 0.0
        # Stomp
        self.stomp_start_height = 0.0

        # Fake jump detection
        self.land_time = 0.0
        self.pre_land_dir = [0.0, 0.0]  # horizontal wish dir before landing
        self.last_wish_dir = [0.0, 0.0]

        # Bunny hop
        self.bhop_window = False
        self.bhop_hit = False  # true on frame a perfect bhop lands
        self.just_landed = False  # true on the frame the player lands

        # Dash cooldown
        self.dash_cooldown_timer = 0.0

        # Space held tracking
        self.space_held = False
        self.space_just_pressed = False

        # Crouching (slide hold)
        self.crouching = False

        # Double-tap tracking for dash
        self.last_space_press_time = 0.0
        self.prev_space_press_time = 0.0  # the press before last

        # Bhop (landing-based)
        self.last_land_time = 0.0  # time.time() when last landed from airborne
        self.bhop_eligible = False  # True if this landing can trigger bhop

        # Bhop visual feedback
        self.bhop_feedback = ""       # "PERFECT" / "GOOD" / "MISS"
        self.bhop_feedback_timer = 0.0
        self.bhop_feedback_timing = 0.0  # the actual time_since_land when space was pressed
        self.bhop_bar_active = False   # show the timing bar

        # Player health
        self.hp = PLAYER_MAX_HP
        self.alive = True
        self.death_timer = 0.0  # countdown before respawn

        # Shotgun
        self.shotgun_cooldown = 0.0
        self.pellets = []  # list of [pos_x, pos_y, pos_z, vel_x, vel_y, vel_z, life]

        # Ammonite corpse combo
        self.ammonite_combo = 0
        self.ammonite_combo_timer = 0.0

        # Stats
        self.speed = 0.0
        self.max_height_reached = 0.0

    def horizontal_speed(self):
        return math.sqrt(self.vel[0] ** 2 + self.vel[2] ** 2)

    def get_forward(self):
        """Forward vector on XZ plane based on yaw."""
        rad = math.radians(self.yaw)
        return [math.sin(rad), 0.0, -math.cos(rad)]

    def get_right(self):
        """Right vector on XZ plane based on yaw."""
        rad = math.radians(self.yaw + 90)
        return [math.sin(rad), 0.0, -math.cos(rad)]

    def get_look_dir(self):
        """Full 3D look direction."""
        yaw_rad = math.radians(self.yaw)
        pitch_rad = math.radians(self.pitch)
        return [
            math.sin(yaw_rad) * math.cos(pitch_rad),
            math.sin(pitch_rad),
            -math.cos(yaw_rad) * math.cos(pitch_rad),
        ]


def accelerate(vel, wish_dir, wish_speed, accel, dt):
    """Quake-style acceleration."""
    current_speed = vel[0] * wish_dir[0] + vel[2] * wish_dir[2]
    add_speed = wish_speed - current_speed
    if add_speed <= 0:
        return vel
    accel_speed = accel * wish_speed * dt
    if accel_speed > add_speed:
        accel_speed = add_speed
    return [
        vel[0] + accel_speed * wish_dir[0],
        vel[1],
        vel[2] + accel_speed * wish_dir[2],
    ]


def apply_friction(vel, friction, dt):
    """Ground friction."""
    speed = math.sqrt(vel[0] ** 2 + vel[2] ** 2)
    if speed < 1.0:
        return [0.0, vel[1], 0.0]
    drop = speed * friction * dt
    new_speed = max(speed - drop, 0.0) / speed
    return [vel[0] * new_speed, vel[1], vel[2] * new_speed]


def normalize_xz(v):
    """Normalize XZ components."""
    length = math.sqrt(v[0] ** 2 + v[2] ** 2)
    if length < 0.001:
        return [0.0, 0.0, 0.0]
    return [v[0] / length, 0.0, v[2] / length]


def dot_xz(a, b):
    return a[0] * b[0] + a[2] * b[2]


def get_wish_dir(keys, player):
    """Calculate wish direction from WASD input relative to view."""
    forward = player.get_forward()
    right = player.get_right()
    wish = [0.0, 0.0, 0.0]
    moving = False
    if keys[K_w]:
        wish[0] += forward[0]; wish[2] += forward[2]; moving = True
    if keys[K_s]:
        wish[0] -= forward[0]; wish[2] -= forward[2]; moving = True
    if keys[K_a]:
        wish[0] -= right[0]; wish[2] -= right[2]; moving = True
    if keys[K_d]:
        wish[0] += right[0]; wish[2] += right[2]; moving = True
    if not moving:
        return [0.0, 0.0, 0.0], False
    return normalize_xz(wish), True


def has_direction_input(keys):
    return keys[K_w] or keys[K_s] or keys[K_a] or keys[K_d]


def is_diagonal(keys):
    horiz = (1 if keys[K_d] else 0) - (1 if keys[K_a] else 0)
    vert = (1 if keys[K_w] else 0) - (1 if keys[K_s] else 0)
    return horiz != 0 and vert != 0


def update_player(player, keys, dt):
    """Main physics update."""
    wish_dir, has_wish = get_wish_dir(keys, player)
    player.last_wish_dir = [wish_dir[0], wish_dir[2]]
    player.bhop_hit = False
    player.just_landed = False
    if player.bhop_feedback_timer > 0:
        player.bhop_feedback_timer -= dt

    # Expire bhop window if too much time has passed
    if player.bhop_eligible and (time.time() - player.last_land_time) > BHOP_WINDOW * 1.2:
        player.bhop_eligible = False
        player.bhop_bar_active = False

    # Dash cooldown tick
    if player.dash_cooldown_timer > 0:
        player.dash_cooldown_timer -= dt

    # Speed for diagonal bonus
    wish_speed = GROUND_MAX_SPEED
    if is_diagonal(keys):
        wish_speed *= DIAGONAL_BONUS

    # =========================================================================
    # State machine
    # =========================================================================

    if player.state == STATE_GROUND:
        # Apply friction
        player.vel = apply_friction(player.vel, GROUND_FRICTION, dt)

        # Ground acceleration
        if has_wish:
            player.vel = accelerate(player.vel, wish_dir, wish_speed, GROUND_ACCEL, dt)

        # Jump / Slide initiation
        if player.space_just_pressed:
            # Check for fake jump (momentum reversal on landing)
            now = time.time()
            if now - player.land_time < FAKE_JUMP_WINDOW and has_wish:
                # Check if current wish is opposite to pre-land direction
                dot = (player.pre_land_dir[0] * wish_dir[0] +
                       player.pre_land_dir[1] * wish_dir[2])
                if dot < -0.3:
                    # Fake jump: reverse horizontal velocity
                    h_speed = player.horizontal_speed()
                    player.vel[0] = wish_dir[0] * h_speed * 1.1
                    player.vel[2] = wish_dir[2] * h_speed * 1.1

            # Check for bhop bonus (jumping shortly after landing)
            if player.bhop_eligible:
                time_since_land = now - player.last_land_time
                player.bhop_feedback_timing = time_since_land
                if time_since_land <= BHOP_WINDOW:
                    if time_since_land <= BHOP_PERFECT_WINDOW:
                        quality = 1.0 - (time_since_land / BHOP_PERFECT_WINDOW)
                        boost = BHOP_BASE_BOOST + (BHOP_SPEED_BOOST - BHOP_BASE_BOOST) * quality
                        player.bhop_feedback = "PERFECT"
                    else:
                        boost = BHOP_BASE_BOOST
                        player.bhop_feedback = "GOOD"
                    # Redirect velocity toward wish direction on bhop
                    h_speed = player.horizontal_speed() * boost
                    if has_wish:
                        # Blend: better timing = more redirection toward wish dir
                        if time_since_land <= BHOP_PERFECT_WINDOW:
                            redirect = 0.6 + 0.4 * quality  # 0.6-1.0 for perfect
                        else:
                            redirect = 0.3  # slight redirect for good
                        player.vel[0] = (1 - redirect) * player.vel[0] * boost + redirect * wish_dir[0] * h_speed
                        player.vel[2] = (1 - redirect) * player.vel[2] * boost + redirect * wish_dir[2] * h_speed
                    else:
                        player.vel[0] *= boost
                        player.vel[2] *= boost
                    player.bhop_hit = True
                else:
                    player.bhop_feedback = "MISS"
                player.bhop_feedback_timer = 1.5
                player.bhop_eligible = False
                player.bhop_bar_active = False
                # Reset dash double-tap so bhop doesn't accidentally trigger a dash
                player.prev_space_press_time = 0.0

            # Jump
            player.vel[1] = JUMP_VELOCITY
            player.state = STATE_AIRBORNE
            player.has_dashed = False
            player.bhop_window = False
        else:
            # Keep on ground (only when NOT jumping)
            player.pos[1] = player.current_height
            player.vel[1] = 0.0

    elif player.state == STATE_AIRBORNE:
        # Gravity
        player.vel[1] -= GRAVITY * dt

        # Air strafing (Quake-style)
        if has_wish:
            player.vel = accelerate(player.vel, wish_dir, AIR_MAX_SPEED, AIR_ACCEL, dt)

        # Track max height for stomp radius
        if player.pos[1] > player.max_height_reached:
            player.max_height_reached = player.pos[1]

        # Space pressed while airborne
        if player.space_just_pressed and not player.has_dashed and player.dash_cooldown_timer <= 0:
            doubletap_gap = player.last_space_press_time - player.prev_space_press_time
            doubletap_ok = DASH_DOUBLETAP_MIN <= doubletap_gap <= DASH_DOUBLETAP_MAX
            if has_wish and doubletap_ok:
                # Start a dash — type is resolved dynamically during dash
                # Pure side dashes are always "normal" (no fast/slide variant)
                has_pure_side = ((keys[K_a] or keys[K_d]) and
                                 not keys[K_w] and not keys[K_s])
                # Dash in the direction the player is looking (full 3D)
                look = player.get_look_dir()
                player.dash_dir = [look[0], look[1], look[2]]
                player.dash_type = "normal"
                player.dash_duration = DASH_DURATION
                player.dash_can_upgrade = not has_pure_side
                impulse = DASH_IMPULSE
                player.vel[0] = player.dash_dir[0] * impulse
                player.vel[1] = player.dash_dir[1] * impulse
                player.vel[2] = player.dash_dir[2] * impulse
                player.state = STATE_DASHING
                player.dash_timer = 0.0
                player.has_dashed = True
                player.dash_cooldown_timer = DASH_COOLDOWN
            elif not has_wish:
                # Stomp: space with no direction
                player.stomp_start_height = player.pos[1]
                player.vel[0] *= 0.1
                player.vel[2] *= 0.1
                player.vel[1] = STOMP_VELOCITY
                player.state = STATE_STOMPING

        # Landing check
        if player.pos[1] <= player.current_height:
            _land(player)

    elif player.state == STATE_DASHING:
        player.dash_timer += dt

        # Dynamically resolve dash type based on ongoing input
        if player.dash_can_upgrade:
            if not player.space_held and not has_wish:
                # Released everything quickly -> fast dash
                if player.dash_type == "normal":
                    player.dash_type = "fast"
                    player.dash_duration = FAST_DASH_DURATION
                    # Boost speed for fast dash (all 3 axes)
                    speed_ratio = FAST_DASH_IMPULSE / DASH_IMPULSE
                    player.vel[0] *= speed_ratio
                    player.vel[1] *= speed_ratio
                    player.vel[2] *= speed_ratio
            elif player.space_held and player.dash_type == "normal":
                # Holding space -> slide dash
                player.dash_type = "slide"
                player.dash_duration = SLIDE_DASH_DURATION
                # Slow down for slide dash (all 3 axes)
                speed_ratio = SLIDE_DASH_IMPULSE / DASH_IMPULSE
                player.vel[0] *= speed_ratio
                player.vel[1] *= speed_ratio
                player.vel[2] *= speed_ratio

        # 2-stage dash: aggressive drag bleeds the initial burst into a slower glide
        drag = math.exp(-DASH_DRAG * dt)
        player.vel[0] *= drag
        player.vel[1] *= drag  # drag applies to full 3D dash direction
        player.vel[2] *= drag

        # Slight steering mid-dash
        if has_wish:
            steer = DASH_STEER_RATE * dt
            player.vel[0] += wish_dir[0] * steer * abs(player.vel[0] + 1)
            player.vel[2] += wish_dir[2] * steer * abs(player.vel[2] + 1)

        # Gravity scaled by how horizontal the dash is (less gravity when dashing vertically)
        vert_component = abs(player.dash_dir[1])
        gravity_scale = 0.3 * (1.0 - vert_component * 0.9)  # near-zero gravity when dashing straight down/up
        player.vel[1] -= GRAVITY * gravity_scale * dt

        # Check if dash is over
        if player.dash_timer >= player.dash_duration:
            if player.pos[1] <= player.current_height + 5.0:
                # Near ground — transition to slide or land
                if player.space_held:
                    player.pos[1] = player.current_height
                    player.vel[1] = 0.0
                    player.state = STATE_SLIDING
                    player.slide_timer = 0.0
                    player.current_height = PLAYER_CROUCH_HEIGHT
                else:
                    _land(player)
            else:
                # Still in the air — just go airborne with current momentum
                player.state = STATE_AIRBORNE

        # Landing during dash
        if player.state == STATE_DASHING and player.pos[1] <= player.current_height:
            if player.space_held:
                player.pos[1] = player.current_height
                player.vel[1] = 0.0
                player.state = STATE_SLIDING
                player.slide_timer = 0.0
                player.current_height = PLAYER_CROUCH_HEIGHT
            else:
                _land(player)

    elif player.state == STATE_SLIDING:
        player.slide_timer += dt
        player.current_height = PLAYER_CROUCH_HEIGHT

        # Sliding friction (very low - preserve momentum)
        player.vel = apply_friction(player.vel, SLIDE_FRICTION, dt)

        # Keep on ground
        player.pos[1] = player.current_height
        player.vel[1] = 0.0

        # Slight steering while sliding
        if has_wish:
            steer = 3.0 * dt
            speed = player.horizontal_speed()
            player.vel[0] += wish_dir[0] * steer * speed * 0.3
            player.vel[2] += wish_dir[2] * steer * speed * 0.3

        # End slide conditions
        if not player.space_held:
            # Release space = stand up, go to ground (no auto-jump)
            player.state = STATE_GROUND
            player.current_height = PLAYER_HEIGHT
            player.pos[1] = PLAYER_HEIGHT
            player.crouching = False
        elif player.slide_timer > SLIDE_MAX_DURATION:
            # Past max duration: ramp up friction smoothly to bleed speed
            overtime = player.slide_timer - SLIDE_MAX_DURATION
            extra_friction = SLIDE_FRICTION + overtime * 15.0  # escalating drag
            player.vel = apply_friction(player.vel, extra_friction, dt)
            if player.space_held:
                player.crouching = True

        # If momentum is very low, stay crouched if holding space
        if player.state == STATE_SLIDING and player.horizontal_speed() < 1.0:
            if player.space_held:
                player.crouching = True
            else:
                player.state = STATE_GROUND

        if player.state != STATE_SLIDING:
            player.current_height = PLAYER_HEIGHT
            player.crouching = False

    elif player.state == STATE_STOMPING:
        # Pure downward velocity, minimal horizontal
        player.vel[1] -= GRAVITY * 1.5 * dt  # extra gravity for fast drop
        damp = max(0.0, 1.0 - 3.0 * dt)  # frame-rate independent damping
        player.vel[0] *= damp
        player.vel[2] *= damp

        if player.pos[1] <= PLAYER_HEIGHT:
            # Stomp landing
            stomp_height = player.stomp_start_height - PLAYER_HEIGHT
            stomp_radius = max(50.0, stomp_height * 0.5)
            player.pos[1] = PLAYER_HEIGHT
            player.vel[1] = 0.0
            # Small bounce if not at apex (penalty for bad timing)
            if stomp_height < JUMP_VELOCITY * 0.3:
                player.vel[1] = JUMP_VELOCITY * 0.3  # bounce
            player.vel[0] *= 0.3
            player.vel[2] *= 0.3
            player.state = STATE_GROUND
            player.current_height = PLAYER_HEIGHT
            player.has_dashed = False
            player.max_height_reached = PLAYER_HEIGHT
            player.land_time = time.time()
            player.last_land_time = time.time()
            player.bhop_eligible = True
            player.bhop_bar_active = True
            player.just_landed = True

    # =========================================================================
    # Position update
    # =========================================================================
    player.pos[0] += player.vel[0] * dt
    player.pos[1] += player.vel[1] * dt
    player.pos[2] += player.vel[2] * dt

    # Floor clamp
    if player.pos[1] < player.current_height and player.state not in (STATE_STOMPING,):
        if player.state in (STATE_AIRBORNE, STATE_DASHING):
            _land(player)
        player.pos[1] = player.current_height
        if player.state in (STATE_GROUND, STATE_SLIDING):
            player.vel[1] = 0.0

    # Update speed readout
    player.speed = player.horizontal_speed()


def _land(player):
    """Handle landing on ground."""
    player.pos[1] = player.current_height
    player.vel[1] = 0.0
    player.pre_land_dir = list(player.last_wish_dir)
    player.land_time = time.time()
    player.max_height_reached = PLAYER_HEIGHT
    player.has_dashed = False

    # Bhop: landing starts the timing window
    player.last_land_time = time.time()
    player.bhop_eligible = True
    player.bhop_bar_active = True
    player.just_landed = True

    if player.space_held:
        # Land into slide
        player.state = STATE_SLIDING
        player.slide_timer = 0.0
        player.current_height = PLAYER_CROUCH_HEIGHT
    else:
        player.state = STATE_GROUND
        player.current_height = PLAYER_HEIGHT


def fire_shotgun(player):
    """Spawn shotgun pellets in a random spread pattern."""
    look = player.get_look_dir()
    # Build an orthonormal basis from look direction
    up = [0.0, 1.0, 0.0]
    # Right = look x up
    right = [
        look[1] * up[2] - look[2] * up[1],
        look[2] * up[0] - look[0] * up[2],
        look[0] * up[1] - look[1] * up[0],
    ]
    r_len = math.sqrt(right[0]**2 + right[1]**2 + right[2]**2)
    if r_len < 0.001:
        right = [1.0, 0.0, 0.0]
    else:
        right = [right[0]/r_len, right[1]/r_len, right[2]/r_len]
    # Recalc up = right x look
    up = [
        right[1] * look[2] - right[2] * look[1],
        right[2] * look[0] - right[0] * look[2],
        right[0] * look[1] - right[1] * look[0],
    ]

    for _ in range(SHOTGUN_PELLET_COUNT):
        # Random offset in cone
        angle = random.uniform(0, 2 * math.pi)
        radius = random.gauss(0, SHOTGUN_SPREAD * 0.5)
        radius = max(-SHOTGUN_SPREAD, min(SHOTGUN_SPREAD, radius))
        rad_offset = math.radians(radius)
        dx = math.cos(angle) * rad_offset
        dy = math.sin(angle) * rad_offset

        # Pellet direction
        d = [
            look[0] + right[0] * dx + up[0] * dy,
            look[1] + right[1] * dx + up[1] * dy,
            look[2] + right[2] * dx + up[2] * dy,
        ]
        d_len = math.sqrt(d[0]**2 + d[1]**2 + d[2]**2)
        d = [d[0]/d_len, d[1]/d_len, d[2]/d_len]

        # Spawn slightly in front of player
        pellet = [
            player.pos[0] + look[0] * 10,
            player.pos[1] + look[1] * 10,
            player.pos[2] + look[2] * 10,
            d[0] * SHOTGUN_PELLET_SPEED,
            d[1] * SHOTGUN_PELLET_SPEED,
            d[2] * SHOTGUN_PELLET_SPEED,
            SHOTGUN_PELLET_LIFETIME,
        ]
        player.pellets.append(pellet)

    # Knockback: scales with how vertical the shot is
    # |look[1]| = 1 when aiming straight up/down (full thrust)
    # |look[1]| = 0 when aiming horizontally (minimal thrust)
    vert_factor = abs(look[1])  # 0.0 (horizontal) to 1.0 (vertical)
    horiz_scale = 0.05 + 0.15 * vert_factor  # 0.05 to 0.2
    vert_scale = 0.1 + 0.9 * vert_factor  # 0.1 to 1.0
    player.vel[0] -= look[0] * SHOTGUN_KNOCKBACK * horiz_scale
    player.vel[1] -= look[1] * SHOTGUN_KNOCKBACK * vert_scale
    player.vel[2] -= look[2] * SHOTGUN_KNOCKBACK * horiz_scale

    # If on ground and shooting downward, launch into air
    if player.state == STATE_GROUND and look[1] < -0.3:
        player.state = STATE_AIRBORNE
        player.has_dashed = False


def update_pellets(player, dt):
    """Update pellet positions and lifetimes."""
    player.shotgun_cooldown = max(0.0, player.shotgun_cooldown - dt)
    alive = []
    for p in player.pellets:
        p[6] -= dt  # life
        if p[6] <= 0:
            continue
        p[0] += p[3] * dt
        p[1] += p[4] * dt
        p[2] += p[5] * dt
        # Pellets hit the ground
        if p[1] <= 0:
            continue
        alive.append(p)
    player.pellets = alive


def draw_pellets(player):
    """Render pellets as bright streaks with short trails."""
    if not player.pellets:
        return
    glDisable(GL_DEPTH_TEST)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    # Draw trails as lines
    glLineWidth(2.0)
    glBegin(GL_LINES)
    for p in player.pellets:
        alpha = min(1.0, p[6] / SHOTGUN_PELLET_LIFETIME * 2)
        # Trail: line from current pos back along velocity
        trail_len = 0.015  # seconds of trail
        tx = p[0] - p[3] * trail_len
        ty = p[1] - p[4] * trail_len
        tz = p[2] - p[5] * trail_len
        # Bright head
        glColor4f(1.0, 0.95, 0.6, alpha)
        glVertex3f(p[0], p[1], p[2])
        # Dim tail
        glColor4f(1.0, 0.6, 0.2, alpha * 0.3)
        glVertex3f(tx, ty, tz)
    glEnd()

    # Draw bright head points
    glPointSize(3.0)
    glBegin(GL_POINTS)
    for p in player.pellets:
        alpha = min(1.0, p[6] / SHOTGUN_PELLET_LIFETIME * 2)
        glColor4f(1.0, 0.95, 0.7, alpha)
        glVertex3f(p[0], p[1], p[2])
    glEnd()
    glEnable(GL_DEPTH_TEST)


# =============================================================================
# Enemies - Flaming Skulls
# =============================================================================

SKULL_ACCEL = 831.0  # how fast skulls accelerate toward player
SKULL_DRAG = 2.0  # air drag on skull velocity
SKULL_TARGET_HEIGHT_BASE = PLAYER_HEIGHT * 0.9  # base hover height
SKULL_HEIGHT_ACCEL = 300.0  # vertical correction force


class Skull:
    def __init__(self, x, z, launch_vel=None):
        self.pos = [x, PLAYER_HEIGHT * 0.9, z]
        self.vel = [0.0, 0.0, 0.0]  # full 3D velocity with momentum
        if launch_vel is not None:
            self.pos[1] = 120.0  # start at spawner height
        self.hp = SKULL_HP
        self.max_hp = SKULL_HP
        self.alive = True
        self.bob_phase = random.uniform(0, math.pi * 2)
        self.fire_phase = random.uniform(0, math.pi * 2)
        self.weakspot_angle = 0.0
        self.damage_numbers = []
        self.hover_offset = random.uniform(-30, 120)  # varied flying heights

    def weakspot_pos(self):
        """World position of the weak spot (back of skull)."""
        # Weak spot sits at the center-back, slightly raised
        wx = self.pos[0] + math.cos(self.weakspot_angle) * SKULL_RADIUS * 0.6
        wy = self.pos[1] + SKULL_RADIUS * 0.3
        wz = self.pos[2] + math.sin(self.weakspot_angle) * SKULL_RADIUS * 0.6
        return [wx, wy, wz]


def update_skulls(skulls, player, dt):
    """Move skulls toward player with full 3D momentum. Remove fully dead skulls."""
    alive_skulls = []
    for skull in skulls:
        # Always tick damage numbers (alive or dead)
        alive_nums = []
        for dn in skull.damage_numbers:
            dn[4] -= dt
            dn[2] += 60.0 * dt
            if dn[4] > 0:
                alive_nums.append(dn)
        skull.damage_numbers = alive_nums

        if not skull.alive and not skull.damage_numbers:
            continue
        alive_skulls.append(skull)

        if not skull.alive:
            continue

        # 3D direction to player
        dx = player.pos[0] - skull.pos[0]
        dy = player.pos[1] - skull.pos[1]
        dz = player.pos[2] - skull.pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)

        if dist > 1.0:
            # Accelerate toward player (3D)
            nx, ny, nz = dx / dist, dy / dist, dz / dist
            skull.vel[0] += nx * SKULL_ACCEL * dt
            skull.vel[1] += ny * SKULL_ACCEL * dt
            skull.vel[2] += nz * SKULL_ACCEL * dt

        # Vertical correction: loose spring toward varied hover height (floaty swarm)
        skull.bob_phase += dt * 2.5
        target_y = SKULL_TARGET_HEIGHT_BASE + skull.hover_offset + math.sin(skull.bob_phase) * 15.0
        height_err = target_y - skull.pos[1]
        skull.vel[1] += height_err * 1.0 * dt  # very soft spring - floaty

        # Drag (limits top speed, gives weight/momentum feel)
        drag = math.exp(-SKULL_DRAG * dt)
        skull.vel[0] *= drag
        skull.vel[1] *= drag
        skull.vel[2] *= drag

        # Clamp max speed
        speed = math.sqrt(skull.vel[0]**2 + skull.vel[1]**2 + skull.vel[2]**2)
        if speed > SKULL_SPEED:
            scale = SKULL_SPEED / speed
            skull.vel[0] *= scale
            skull.vel[1] *= scale
            skull.vel[2] *= scale

        # Apply velocity
        skull.pos[0] += skull.vel[0] * dt
        skull.pos[1] += skull.vel[1] * dt
        skull.pos[2] += skull.vel[2] * dt

        # Don't go below ground
        if skull.pos[1] < SKULL_RADIUS:
            skull.pos[1] = SKULL_RADIUS
            skull.vel[1] = max(0, skull.vel[1])

        # Face the player - weak spot is on the back
        skull.weakspot_angle = math.atan2(-dz, -dx)

        # Check collision with player (3D distance)
        if player.alive and dist < SKULL_KILL_RADIUS:
            player.hp = 0
            player.alive = False
            player.death_timer = 2.0

    # Skull-skull collision: push overlapping skulls apart
    alive_only = [s for s in alive_skulls if s.alive]
    for i in range(len(alive_only)):
        for j in range(i + 1, len(alive_only)):
            a = alive_only[i]
            b = alive_only[j]
            dx = b.pos[0] - a.pos[0]
            dy = b.pos[1] - a.pos[1]
            dz = b.pos[2] - a.pos[2]
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            min_dist = SKULL_RADIUS * 2.2  # slight gap between skulls
            if dist < min_dist and dist > 0.01:
                # Push apart along separation axis
                overlap = min_dist - dist
                nx, ny, nz = dx / dist, dy / dist, dz / dist
                push = overlap * 0.5
                a.pos[0] -= nx * push
                a.pos[1] -= ny * push
                a.pos[2] -= nz * push
                b.pos[0] += nx * push
                b.pos[1] += ny * push
                b.pos[2] += nz * push
                # Also deflect velocities apart
                a.vel[0] -= nx * 50 * dt
                a.vel[1] -= ny * 50 * dt
                a.vel[2] -= nz * 50 * dt
                b.vel[0] += nx * 50 * dt
                b.vel[1] += ny * 50 * dt
                b.vel[2] += nz * 50 * dt

    return alive_skulls


# =============================================================================
# Spawners - Rotating Diamond Structures
# =============================================================================

SPAWN_IN_DURATION = 4.0  # seconds for entities to materialize

class Spawner:
    def __init__(self, x, z, instant=False):
        self.pos = [x, 120.0, z]  # float above ground
        self.hp = SPAWNER_HP
        self.max_hp = SPAWNER_HP
        self.alive = True
        self.spawn_timer = random.uniform(5.0, SPAWNER_SPAWN_INTERVAL)  # stagger first spawn
        self.rotation = random.uniform(0, 360)
        self.phase = random.uniform(0, math.pi * 2)
        self.damage_numbers = []
        self.spawn_queue = 0  # skulls waiting to be spewed out
        self.spawn_tick = 0.0  # timer between individual skull launches
        self.spawn_in_timer = 0.0 if instant else SPAWN_IN_DURATION  # telegraph before appearing
        self.spawning_in = not instant

    def flash_rate(self):
        """Returns flashes per second based on how close to spawning."""
        if self.spawn_timer > 10.0:
            return 1.0
        elif self.spawn_timer > 5.0:
            return 3.0
        elif self.spawn_timer > 2.0:
            return 8.0
        else:
            return 20.0


def create_spawners(player_pos, count=SPAWNER_COUNT):
    """Create initial spawner structures around the player."""
    spawners = []
    for _ in range(count):
        angle = random.uniform(0, math.pi * 2)
        dist = random.uniform(SPAWNER_MIN_DIST, SPAWNER_SPAWN_RANGE)
        x = player_pos[0] + math.cos(angle) * dist
        z = player_pos[2] + math.sin(angle) * dist
        spawners.append(Spawner(x, z, instant=True))
    return spawners


def update_spawners(spawners, skulls, player, dt):
    """Update spawners: rotate, tick spawn timer, spawn skulls, tick damage numbers."""
    alive_spawners = []
    for sp in spawners:
        # Tick damage numbers
        alive_nums = []
        for dn in sp.damage_numbers:
            dn[4] -= dt
            dn[2] += 60.0 * dt
            if dn[4] > 0:
                alive_nums.append(dn)
        sp.damage_numbers = alive_nums

        if not sp.alive and not sp.damage_numbers:
            continue  # fully gone
        alive_spawners.append(sp)

        if not sp.alive:
            continue

        # Spawn-in telegraph
        if sp.spawning_in:
            sp.spawn_in_timer -= dt
            sp.rotation += 90.0 * dt  # spin faster while spawning in
            if sp.spawn_in_timer <= 0:
                sp.spawning_in = False
            continue  # don't do anything else while spawning in

        # Rotate
        sp.rotation += 45.0 * dt  # degrees per second

        # Bob gently
        sp.phase += dt * 1.5
        sp.pos[1] = 120.0 + math.sin(sp.phase) * 12.0

        # Regenerate health continuously
        if sp.hp < sp.max_hp:
            sp.hp = min(sp.max_hp, sp.hp + SPAWNER_REGEN * dt)

        # Spawn timer - queue up skulls when ready
        sp.spawn_timer -= dt
        if sp.spawn_timer <= 0 and sp.spawn_queue == 0:
            sp.spawn_queue = min(15, SKULL_MAX - len(skulls))
            sp.spawn_tick = 0.0
            sp.spawn_timer = SPAWNER_SPAWN_INTERVAL

        # Spew queued skulls one at a time
        if sp.spawn_queue > 0:
            sp.spawn_tick -= dt
            if sp.spawn_tick <= 0:
                skull = Skull(sp.pos[0], sp.pos[2])
                skull.pos[1] = sp.pos[1] + SPAWNER_RADIUS * 0.8
                # Volcanic eruption - blast them skyward
                angle = random.uniform(0, math.pi * 2)
                horiz_spread = random.uniform(800, 2400)
                skull.vel[0] = math.cos(angle) * horiz_spread
                skull.vel[1] = random.uniform(20000, 32000)  # volcanic eruption
                skull.vel[2] = math.sin(angle) * horiz_spread
                skulls.append(skull)
                sp.spawn_queue -= 1
                sp.spawn_tick = 0.08  # 80ms between each skull

        # Kill player on touch
        if player.alive:
            dx = player.pos[0] - sp.pos[0]
            dy = player.pos[1] - sp.pos[1]
            dz = player.pos[2] - sp.pos[2]
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist < SPAWNER_RADIUS:
                player.hp = 0
                player.alive = False
                player.death_timer = 2.0

    return alive_spawners


def check_pellet_hits_spawners(player, spawners):
    """Check pellet collisions with spawners."""
    alive_pellets = []
    for p in player.pellets:
        hit = False
        px, py, pz = p[0], p[1], p[2]
        for sp in spawners:
            if not sp.alive:
                continue
            dx = px - sp.pos[0]
            dy = py - sp.pos[1]
            dz = pz - sp.pos[2]
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist < SPAWNER_RADIUS:
                dmg = SPAWNER_PELLET_DAMAGE
                sp.hp -= dmg
                sp.damage_numbers.append([
                    str(dmg), px, py + SPAWNER_RADIUS + 10, pz,
                    0.6, (0.5, 0.8, 1.0)  # cyan for spawner hits
                ])
                if sp.hp <= 0:
                    sp.alive = False
                hit = True
                break
        if not hit:
            alive_pellets.append(p)
    player.pellets = alive_pellets


def draw_spawners(spawners, sphere_dl=None):
    """Render spawners as large rotating diamond/rhombus structures."""
    fire_t = g_frame_time

    for sp in spawners:
        if not sp.alive:
            # Still draw damage numbers via 2D pass
            continue

        x, y, z = sp.pos
        size = SPAWNER_RADIUS * 1.5  # visual size larger than collision

        # Spawn-in hologram rendering
        if sp.spawning_in:
            spawn_frac = 1.0 - (sp.spawn_in_timer / SPAWN_IN_DURATION)  # 0->1
            flicker = 0.5 + 0.5 * math.sin(fire_t * (10 + spawn_frac * 20))
            alpha = spawn_frac * 0.6 * flicker

            glPushMatrix()
            glTranslatef(x, y, z)
            glRotatef(sp.rotation, 0, 1, 0)

            eq = size * 0.7
            sides = [[eq, 0, 0], [0, 0, eq], [-eq, 0, 0], [0, 0, -eq]]
            top = [0, size, 0]
            bottom = [0, -size, 0]

            # Wireframe diamond hologram
            glLineWidth(2.0)
            glColor4f(0.3, 0.5 + flicker * 0.3, 1.0, alpha)
            glBegin(GL_LINES)
            for i in range(4):
                s1 = sides[i]
                s2 = sides[(i + 1) % 4]
                glVertex3f(top[0], top[1], top[2])
                glVertex3f(s1[0], s1[1], s1[2])
                glVertex3f(bottom[0], bottom[1], bottom[2])
                glVertex3f(s1[0], s1[1], s1[2])
                glVertex3f(s1[0], s1[1], s1[2])
                glVertex3f(s2[0], s2[1], s2[2])
            glEnd()

            # Translucent faces
            glColor4f(0.2, 0.4, 1.0, alpha * 0.3)
            glBegin(GL_TRIANGLES)
            for i in range(4):
                s1 = sides[i]
                s2 = sides[(i + 1) % 4]
                glVertex3f(top[0], top[1], top[2])
                glVertex3f(s1[0], s1[1], s1[2])
                glVertex3f(s2[0], s2[1], s2[2])
                glVertex3f(bottom[0], bottom[1], bottom[2])
                glVertex3f(s2[0], s2[1], s2[2])
                glVertex3f(s1[0], s1[1], s1[2])
            glEnd()

            glPopMatrix()
            continue

        # Flash rate increases as spawn approaches
        flash_rate = sp.flash_rate()
        flash = 0.5 + 0.5 * math.sin(fire_t * flash_rate * math.pi * 2)

        # Base color: dark purple/crimson, brightens with flash
        base_r = 0.4 + flash * 0.5
        base_g = 0.05 + flash * 0.15
        base_b = 0.3 + flash * 0.4

        # HP-based color shift (more red when damaged)
        hp_frac = max(0, sp.hp / sp.max_hp)
        base_g *= hp_frac
        base_b *= hp_frac

        glPushMatrix()
        glTranslatef(x, y, z)
        glRotatef(sp.rotation, 0, 1, 0)  # spin around Y axis only

        # Diamond with blooming top petals
        # bloom_angle: 0 = closed (full HP), ~90° = petals folded flat/outward (0 HP)
        damage_frac = 1.0 - hp_frac  # 0 = full HP, 1 = dead
        bloom_angle = damage_frac * 110.0  # degrees the petals open
        bloom_rad = math.radians(bloom_angle)

        bottom = [0, -size, 0]
        eq = size * 0.7
        # 4 equator vertices (hinge points for petals)
        sides = [
            [eq, 0, 0],
            [0, 0, eq],
            [-eq, 0, 0],
            [0, 0, -eq],
        ]
        # Petal tip directions (outward from center at equator level)
        petal_dirs = [
            [1, 0, 0],
            [0, 0, 1],
            [-1, 0, 0],
            [0, 0, -1],
        ]

        # Compute petal tip positions: rotate the top point around the hinge
        # When closed (bloom_angle=0), tip is at [0, size, 0]
        # When open, tip rotates outward around the equator edge
        petal_tips = []
        for i in range(4):
            # The petal hinges at the midpoint between sides[i] and sides[(i+1)%4]
            s1 = sides[i]
            s2 = sides[(i + 1) % 4]
            hinge_x = (s1[0] + s2[0]) * 0.5
            hinge_z = (s1[2] + s2[2]) * 0.5
            # Direction from center to hinge (outward)
            hd = math.sqrt(hinge_x**2 + hinge_z**2)
            if hd < 0.01:
                hnx, hnz = petal_dirs[i][0], petal_dirs[i][2]
            else:
                hnx, hnz = hinge_x / hd, hinge_z / hd

            # Petal length (from hinge to tip when closed)
            petal_len = size  # same as distance from equator to top
            # Rotate: when closed, tip goes straight up. When open, tip swings outward.
            tip_y = hinge_z * 0 + math.cos(bloom_rad) * petal_len
            tip_outward = math.sin(bloom_rad) * petal_len
            tip_x = hinge_x + hnx * tip_outward
            tip_z = hinge_z + hnz * tip_outward
            petal_tips.append([tip_x, tip_y, tip_z])

        # Inner glow visible when blooming
        if bloom_angle > 10:
            glBegin(GL_QUADS)
            glow_intensity = damage_frac
            glColor4f(1.0, 0.2 + glow_intensity * 0.3, 0.05, glow_intensity * 0.7)
            inner_s = eq * 0.4
            gy = size * 0.3 * hp_frac  # glow sinks as it opens
            glVertex3f(-inner_s, gy, -inner_s)
            glVertex3f(inner_s, gy, -inner_s)
            glVertex3f(inner_s, gy, inner_s)
            glVertex3f(-inner_s, gy, inner_s)
            glEnd()

            # Pulsing core
            core_pulse = 0.5 + 0.5 * math.sin(fire_t * 6)
            glPointSize(8.0 * glow_intensity)
            glBegin(GL_POINTS)
            glColor4f(1.0, 0.4 * core_pulse, 0.1, glow_intensity * 0.8)
            glVertex3f(0, gy, 0)
            glEnd()

        # Draw 4 petals (top faces) + bottom pyramid
        glBegin(GL_TRIANGLES)
        for i in range(4):
            s1 = sides[i]
            s2 = sides[(i + 1) % 4]
            tip = petal_tips[i]
            bright = 0.8 + 0.2 * ((i % 2) == 0)

            # Each petal is a triangle: s1 -> s2 -> tip
            # Inner face (slightly different shade)
            glColor4f(base_r * bright, base_g * bright, base_b * bright, 0.85)
            glVertex3f(tip[0], tip[1], tip[2])
            glVertex3f(s1[0], s1[1], s1[2])
            glVertex3f(s2[0], s2[1], s2[2])

            # Bottom pyramid face (unchanged)
            glColor4f(base_r * bright * 0.6, base_g * bright * 0.6, base_b * bright * 0.6, 0.85)
            glVertex3f(bottom[0], bottom[1], bottom[2])
            glVertex3f(s2[0], s2[1], s2[2])
            glVertex3f(s1[0], s1[1], s1[2])
        glEnd()

        # Edge glow lines
        glLineWidth(2.0)
        glColor4f(1.0, 0.3 + flash * 0.4, 0.5 + flash * 0.3, 0.7)
        glBegin(GL_LINES)
        for i in range(4):
            s1 = sides[i]
            s2 = sides[(i + 1) % 4]
            tip = petal_tips[i]
            # Petal edges
            glVertex3f(tip[0], tip[1], tip[2])
            glVertex3f(s1[0], s1[1], s1[2])
            glVertex3f(tip[0], tip[1], tip[2])
            glVertex3f(s2[0], s2[1], s2[2])
            # Bottom edges
            glVertex3f(bottom[0], bottom[1], bottom[2])
            glVertex3f(s1[0], s1[1], s1[2])
            # Equator edges
            glVertex3f(s1[0], s1[1], s1[2])
            glVertex3f(s2[0], s2[1], s2[2])
        glEnd()

        glPopMatrix()

        # Orbiting particles
        glDisable(GL_DEPTH_TEST)
        glPointSize(3.0)
        glBegin(GL_POINTS)
        for i in range(12):
            orbit_angle = fire_t * 2.0 + i * (math.pi * 2 / 12) + sp.phase
            orbit_r = size * 0.9
            ox = x + math.cos(orbit_angle) * orbit_r
            oy = y + math.sin(orbit_angle * 0.7 + i) * size * 0.4
            oz = z + math.sin(orbit_angle) * orbit_r
            glColor4f(1.0, 0.3 + flash * 0.5, 0.6, 0.6 * flash + 0.3)
            glVertex3f(ox, oy, oz)
        glEnd()
        glEnable(GL_DEPTH_TEST)

        # HP bar above spawner
        if sp.hp < sp.max_hp:
            bar_w = SPAWNER_RADIUS * 3
            bar_y_pos = y + size + 20
            glDisable(GL_DEPTH_TEST)
            glLineWidth(5.0)
            glColor4f(0.3, 0.0, 0.0, 0.7)
            glBegin(GL_LINES)
            glVertex3f(x - bar_w/2, bar_y_pos, z)
            glVertex3f(x + bar_w/2, bar_y_pos, z)
            glEnd()
            r_col = 1.0 - hp_frac
            g_col = hp_frac
            glColor4f(r_col, g_col, 0.0, 0.9)
            glBegin(GL_LINES)
            glVertex3f(x - bar_w/2, bar_y_pos, z)
            glVertex3f(x - bar_w/2 + bar_w * hp_frac, bar_y_pos, z)
            glEnd()
            glEnable(GL_DEPTH_TEST)

        # Spawn preview hologram — show blue skull above spawner when spawn is < 6 seconds away
        if sp.spawn_timer < 6.0 and sp.spawn_queue == 0 and sphere_dl:
            preview_frac = 1.0 - (sp.spawn_timer / 6.0)  # 0 at 6s, 1 at 0s
            # Flash faster as spawn approaches
            flash_speed = 2.0 + preview_frac * 20.0
            flash = 0.5 + 0.5 * math.sin(fire_t * flash_speed)
            # Visibility: starts faint, gets bright + flashy
            base_alpha = 0.15 + preview_frac * 0.6
            alpha = base_alpha * (0.5 + 0.5 * flash)

            glDisable(GL_DEPTH_TEST)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            # Draw large blue skull preview above the spawner
            preview_y = y + size + 80 + math.sin(fire_t * 2) * 20
            skull_preview_r = SKULL_RADIUS * (2.0 + preview_frac * 2.0)
            glColor4f(0.3, 0.5, 1.0, alpha)
            glPushMatrix()
            glTranslatef(x, preview_y, z)
            glScalef(skull_preview_r, skull_preview_r, skull_preview_r)
            glCallList(sphere_dl)
            glPopMatrix()

            # Wispy particles orbiting the preview
            glPointSize(5.0)
            glBegin(GL_POINTS)
            for i in range(8):
                pa = fire_t * 3 + i * (math.pi * 2 / 8)
                pr = skull_preview_r * 2.0
                px = x + math.cos(pa) * pr
                py2 = preview_y + math.sin(pa * 1.3 + i) * skull_preview_r * 0.8
                pz = z + math.sin(pa) * pr
                glColor4f(0.4, 0.6, 1.0, alpha * 0.8)
                glVertex3f(px, py2, pz)
            glEnd()

            glEnable(GL_DEPTH_TEST)


def check_pellet_hits(player, skulls):
    """Check pellet collisions with skulls. Returns list of pellets that are still alive."""
    alive_pellets = []
    for p in player.pellets:
        hit = False
        px, py, pz = p[0], p[1], p[2]
        for skull in skulls:
            if not skull.alive:
                continue
            # Check weak spot first (smaller, higher damage)
            wp = skull.weakspot_pos()
            wdx = px - wp[0]
            wdy = py - wp[1]
            wdz = pz - wp[2]
            w_dist = math.sqrt(wdx*wdx + wdy*wdy + wdz*wdz)
            if w_dist < SKULL_WEAKSPOT_RADIUS:
                dmg = SKULL_PELLET_DAMAGE * SKULL_WEAKSPOT_MULTIPLIER
                skull.hp -= dmg
                skull.damage_numbers.append([
                    str(dmg), px, py + SKULL_RADIUS + 10, pz,
                    0.6, (1.0, 0.9, 0.2)  # yellow for weak spot
                ])
                if skull.hp <= 0:
                    skull.alive = False
                hit = True
                break

            # Check body hit
            bdx = px - skull.pos[0]
            bdy = py - skull.pos[1]
            bdz = pz - skull.pos[2]
            b_dist = math.sqrt(bdx*bdx + bdy*bdy + bdz*bdz)
            if b_dist < SKULL_RADIUS:
                dmg = SKULL_PELLET_DAMAGE
                skull.hp -= dmg
                skull.damage_numbers.append([
                    str(dmg), px, py + SKULL_RADIUS + 10, pz,
                    0.6, (1.0, 1.0, 1.0)  # white for body
                ])
                if skull.hp <= 0:
                    skull.alive = False
                hit = True
                break

        if not hit:
            alive_pellets.append(p)
        # If hit, pellet is consumed (don't add to alive)

    player.pellets = alive_pellets


# =============================================================================
# Ammonites - Big flat floating spiral enemies
# =============================================================================

class Ammonite:
    def __init__(self, x, z, instant=False):
        self.pos = [x, AMMONITE_HOVER_HEIGHT, z]
        self.vel = [0.0, 0.0, 0.0]
        self.hp = AMMONITE_HP
        self.max_hp = AMMONITE_HP
        self.alive = True
        self.rotation = random.uniform(0, 360)
        self.bob_phase = random.uniform(0, math.pi * 2)
        self.damage_numbers = []
        # Corpse state
        self.is_corpse = False
        self.corpse_timer = 0.0
        self.corpse_fall_vel = 0.0
        # Group orbit
        self.group_center = [x, z]  # shared center for orbit
        self.orbit_phase = 0.0  # current angle in orbit
        self.orbit_radius = 200.0  # distance from group center
        self.orbit_speed = random.uniform(0.4, 0.8)  # radians per second
        self.bank_angle = 0.0  # tilt when turning
        self.spawn_in_timer = 0.0 if instant else SPAWN_IN_DURATION  # telegraph before appearing
        self.spawning_in = not instant


_ammonite_group_id = [0]

def _spawn_ammonite_group(cx, cz, instant=False):
    """Spawn a group of 3 ammonites near a center point."""
    group = []
    for i in range(3):
        offset_angle = (i / 3) * math.pi * 2 + random.uniform(-0.3, 0.3)
        offset_dist = random.uniform(240, 540)
        x = cx + math.cos(offset_angle) * offset_dist
        z = cz + math.sin(offset_angle) * offset_dist
        am = Ammonite(x, z, instant=instant)
        am.group_center = [cx, cz]
        am.orbit_phase = (i / 3) * math.pi * 2
        am.orbit_radius = offset_dist
        group.append(am)
    return group


def create_ammonites(player_pos, count=AMMONITE_COUNT):
    """Create initial ammonite groups around the player."""
    ammonites = []
    for _ in range(count):
        angle = random.uniform(0, math.pi * 2)
        dist = random.uniform(AMMONITE_MIN_DIST, AMMONITE_SPAWN_RANGE)
        cx = player_pos[0] + math.cos(angle) * dist
        cz = player_pos[2] + math.sin(angle) * dist
        ammonites.extend(_spawn_ammonite_group(cx, cz, instant=True))
    return ammonites


def update_ammonites(ammonites, player, dt, pickup_sounds=None):
    """Update ammonites: chase when close, handle corpse state."""
    # Tick combo timer
    if player.ammonite_combo_timer > 0:
        player.ammonite_combo_timer -= dt
        if player.ammonite_combo_timer <= 0:
            player.ammonite_combo = 0
    alive_list = []
    for am in ammonites:
        # Tick damage numbers
        alive_nums = []
        for dn in am.damage_numbers:
            dn[4] -= dt
            dn[2] += 60.0 * dt
            if dn[4] > 0:
                alive_nums.append(dn)
        am.damage_numbers = alive_nums

        if not am.alive and not am.is_corpse and not am.damage_numbers:
            continue  # fully gone
        alive_list.append(am)

        # Handle corpse state
        if am.is_corpse:
            # Fall to ground
            am.corpse_fall_vel -= GRAVITY * dt * 0.5
            am.pos[1] += am.corpse_fall_vel * dt
            if am.pos[1] < AMMONITE_RADIUS * 0.3:
                am.pos[1] = AMMONITE_RADIUS * 0.3
                am.corpse_fall_vel = 0.0

            # Spin while falling
            am.rotation += 180.0 * dt

            # Check player pickup
            if player.alive:
                dx = player.pos[0] - am.pos[0]
                dy = player.pos[1] - am.pos[1]
                dz = player.pos[2] - am.pos[2]
                dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                if dist < AMMONITE_CORPSE_RADIUS:
                    # Boost player forward and up
                    look = player.get_look_dir()
                    horiz = math.sqrt(look[0]**2 + look[2]**2)
                    if horiz > 0.01:
                        fwd_x = look[0] / horiz
                        fwd_z = look[2] / horiz
                    else:
                        rad = math.radians(player.yaw)
                        fwd_x = -math.sin(rad)
                        fwd_z = -math.cos(rad)
                    player.vel[0] = fwd_x * AMMONITE_BOOST_FORWARD
                    player.vel[2] = fwd_z * AMMONITE_BOOST_FORWARD
                    player.vel[1] = AMMONITE_BOOST_UP
                    player.pos[1] = player.current_height + 5.0  # lift off ground to prevent floor clamp
                    player.state = STATE_AIRBORNE
                    player.has_dashed = False
                    player.dash_cooldown_timer = 0.0
                    # Play combo sound
                    if pickup_sounds:
                        idx = min(player.ammonite_combo, len(pickup_sounds) - 1)
                        pickup_sounds[idx].play()
                    player.ammonite_combo += 1
                    player.ammonite_combo_timer = 5.0
                    am.is_corpse = False
                    am.alive = False
                    continue

            # Revive timer
            am.corpse_timer -= dt
            if am.corpse_timer <= 0:
                # Revive!
                am.is_corpse = False
                am.alive = True
                am.hp = am.max_hp
                am.pos[1] = AMMONITE_HOVER_HEIGHT
                am.vel = [0.0, 0.0, 0.0]
                am.corpse_fall_vel = 0.0
            continue

        if not am.alive:
            continue

        # Spawn-in telegraph
        if am.spawning_in:
            am.spawn_in_timer -= dt
            am.rotation += 60.0 * dt
            if am.spawn_in_timer <= 0:
                am.spawning_in = False
            continue  # don't move or collide while spawning in

        am.bob_phase += dt * 2.0

        # Distance to player
        dx = player.pos[0] - am.pos[0]
        dy = player.pos[1] - am.pos[1]
        dz = player.pos[2] - am.pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)

        # Chase when close — aggressively pursue the player
        if dist < AMMONITE_AGGRO_RANGE and dist > 1.0:
            nx, ny, nz = dx / dist, dy / dist, dz / dist
            close_factor = 1.0 + (1.0 - dist / AMMONITE_AGGRO_RANGE) * 2.0
            accel = AMMONITE_ACCEL * close_factor
            am.vel[0] += nx * accel * dt
            am.vel[1] += ny * accel * dt
            am.vel[2] += nz * accel * dt
        else:
            # Lazy meandering orbit around group center
            am.orbit_phase += am.orbit_speed * dt
            target_x = am.group_center[0] + math.cos(am.orbit_phase) * am.orbit_radius
            target_z = am.group_center[1] + math.sin(am.orbit_phase) * am.orbit_radius
            ox = target_x - am.pos[0]
            oz = target_z - am.pos[2]
            # Gentle steering toward orbit target
            am.vel[0] += ox * 1.2 * dt
            am.vel[2] += oz * 1.2 * dt

        # Bank into turns — rotation follows movement direction
        hspeed = math.sqrt(am.vel[0]**2 + am.vel[2]**2)
        if hspeed > 5.0:
            target_rot = math.degrees(math.atan2(am.vel[0], am.vel[2]))
            # Smooth rotation toward movement direction
            diff = (target_rot - am.rotation + 180) % 360 - 180
            am.rotation += diff * 3.0 * dt
            # Tilt into the turn based on how hard we're turning
            target_bank = diff * -0.8  # negative = lean into the turn
            target_bank = max(-35.0, min(35.0, target_bank))  # cap at 35 degrees
        else:
            target_bank = 0.0
        # Smooth the bank angle
        am.bank_angle += (target_bank - am.bank_angle) * 4.0 * dt

        # Hover height spring
        target_y = AMMONITE_HOVER_HEIGHT + math.sin(am.bob_phase) * 15.0
        height_err = target_y - am.pos[1]
        am.vel[1] += height_err * 2.0 * dt

        # Drag
        drag = math.exp(-AMMONITE_DRAG * dt)
        am.vel[0] *= drag
        am.vel[1] *= drag
        am.vel[2] *= drag

        # Clamp speed
        speed = math.sqrt(am.vel[0]**2 + am.vel[1]**2 + am.vel[2]**2)
        if speed > AMMONITE_SPEED:
            scale = AMMONITE_SPEED / speed
            am.vel[0] *= scale
            am.vel[1] *= scale
            am.vel[2] *= scale

        # Apply velocity
        am.pos[0] += am.vel[0] * dt
        am.pos[1] += am.vel[1] * dt
        am.pos[2] += am.vel[2] * dt

        if am.pos[1] < AMMONITE_RADIUS:
            am.pos[1] = AMMONITE_RADIUS
            am.vel[1] = max(0, am.vel[1])

        # Kill player on touch
        if player.alive and dist < AMMONITE_KILL_RADIUS:
            player.hp = 0
            player.alive = False
            player.death_timer = 2.0

    return alive_list


def check_pellet_hits_ammonites(player, ammonites):
    """Check pellet collisions with ammonites."""
    alive_pellets = []
    for p in player.pellets:
        hit = False
        px, py, pz = p[0], p[1], p[2]
        for am in ammonites:
            if not am.alive and not am.is_corpse:
                continue
            dx = px - am.pos[0]
            dy = py - am.pos[1]
            dz = pz - am.pos[2]
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist < AMMONITE_RADIUS:
                if am.is_corpse:
                    # Shotgun hit on corpse: add 0.5s, capped at max
                    am.corpse_timer = min(am.corpse_timer + 0.5, AMMONITE_CORPSE_REVIVE)
                    hit = True
                    break
                dmg = AMMONITE_PELLET_DAMAGE
                am.hp -= dmg
                am.damage_numbers.append([
                    str(dmg), px, py + AMMONITE_RADIUS + 10, pz,
                    0.6, (0.4, 1.0, 0.6)  # green for ammonite hits
                ])
                if am.hp <= 0:
                    # Become corpse instead of dying
                    am.alive = False
                    am.is_corpse = True
                    am.corpse_timer = AMMONITE_CORPSE_REVIVE
                    am.corpse_fall_vel = 100.0  # small upward pop
                hit = True
                break
        if not hit:
            alive_pellets.append(p)
    player.pellets = alive_pellets


def draw_ammonites(ammonites, disc_dl=None):
    """Render ammonites as big flat spiral disc creatures using compiled geometry."""
    fire_t = g_frame_time
    r = AMMONITE_RADIUS

    for am in ammonites:
        if not am.alive and not am.is_corpse:
            continue

        x, y, z = am.pos

        # Spawn-in hologram rendering
        if am.spawning_in:
            spawn_frac = 1.0 - (am.spawn_in_timer / SPAWN_IN_DURATION)  # 0->1
            flicker = 0.5 + 0.5 * math.sin(fire_t * (10 + spawn_frac * 20))
            alpha = spawn_frac * 0.6 * flicker

            glPushMatrix()
            glTranslatef(x, y, z)
            glRotatef(am.rotation, 0, 1, 0)

            # Wireframe disc hologram
            glColor4f(0.3, 0.5 + flicker * 0.3, 1.0, alpha)
            glLineWidth(2.0)
            glBegin(GL_LINE_LOOP)
            for i in range(_DISC_SEGS):
                glVertex3f(_disc_cos[i] * r, 0, _disc_sin[i] * r)
            glEnd()

            # Cross lines
            glBegin(GL_LINES)
            glVertex3f(-r, 0, 0)
            glVertex3f(r, 0, 0)
            glVertex3f(0, 0, -r)
            glVertex3f(0, 0, r)
            glEnd()

            # Translucent fill
            glColor4f(0.2, 0.4, 1.0, alpha * 0.2)
            glPushMatrix()
            glScalef(r, r, r)
            if disc_dl:
                glCallList(disc_dl)
            glPopMatrix()

            glPopMatrix()
            continue

        glPushMatrix()
        glTranslatef(x, y, z)
        glRotatef(am.rotation, 0, 1, 0)
        glRotatef(am.bank_angle, 0, 0, 1)  # tilt into turns

        # Corpse: grey/dark, flicker as revive approaches
        if am.is_corpse:
            revive_frac = 1.0 - (am.corpse_timer / AMMONITE_CORPSE_REVIVE)
            flicker = 0.5 + 0.5 * math.sin(fire_t * (5 + revive_frac * 20))
            base_r = 0.2 + revive_frac * 0.5 * flicker
            base_g = 0.2 + revive_frac * 0.3 * flicker
            base_b = 0.15
            alpha = 0.7 + revive_frac * 0.3
            glRotatef(90, 1, 0, 0)
        else:
            shimmer = 0.5 + 0.5 * math.sin(fire_t * 3 + am.bob_phase)
            base_r = 0.6 + shimmer * 0.2
            base_g = 0.35 + shimmer * 0.15
            base_b = 0.1 + shimmer * 0.1
            alpha = 0.9

        # Draw disc body using compiled display list
        glColor4f(base_r * 0.9, base_g * 0.9, base_b, alpha)
        glPushMatrix()
        glScalef(r, r, r)
        if disc_dl:
            glCallList(disc_dl)
        glPopMatrix()

        # Spiral pattern (pre-computed trig)
        thickness = r * 0.25
        glLineWidth(2.5)
        glBegin(GL_LINE_STRIP)
        for t, sc, ss in _spiral_data:
            sr = t * r * 0.85
            glColor4f(base_r * 0.5 + t * 0.5, base_g * 0.3 + t * 0.4, base_b + t * 0.3, alpha)
            glVertex3f(sc * sr, thickness * 0.5 + 1.0, ss * sr)
        glEnd()

        # Radial ribs (pre-computed trig)
        glLineWidth(1.5)
        glBegin(GL_LINES)
        for i in range(0, _DISC_SEGS):
            glColor4f(base_r * 0.7, base_g * 0.7, base_b * 0.5, alpha * 0.6)
            glVertex3f(0, thickness * 0.5 + 0.5, 0)
            glVertex3f(_disc_cos[i] * r * 0.9, thickness * 0.5 + 0.5, _disc_sin[i] * r * 0.9)
        glEnd()

        # Corpse glow
        if am.is_corpse:
            pulse = 0.5 + 0.5 * math.sin(fire_t * 8)
            glPointSize(12.0)
            glBegin(GL_POINTS)
            glColor4f(0.2 + pulse * 0.8, 1.0, 0.3 + pulse * 0.4, 0.8)
            glVertex3f(0, 2.0, 0)
            glEnd()

        glPopMatrix()

    glLineWidth(1.0)


def draw_skulls(skulls, sphere_dl=None):
    """Render flaming skulls with weak spots using compiled display list."""
    fire_t = g_frame_time
    r = SKULL_RADIUS
    wr = SKULL_WEAKSPOT_RADIUS

    for skull in skulls:
        if not skull.alive:
            continue

        x, y, z = skull.pos

        # --- Skull body (compiled sphere) ---
        fire_flicker = 0.05 * math.sin(fire_t * 8 + skull.fire_phase)
        glColor3f(0.75 + fire_flicker, 0.65 + fire_flicker, 0.5)
        glPushMatrix()
        glTranslatef(x, y, z)
        glScalef(r, r, r)
        if sphere_dl:
            glCallList(sphere_dl)
        glPopMatrix()

        # --- Fire particles (reduced count) ---
        glDisable(GL_DEPTH_TEST)
        glPointSize(4.0)
        glBegin(GL_POINTS)
        for i in range(10):
            phase = skull.fire_phase + i * 1.4
            ft = fire_t * 3 + phase
            fx = x + math.sin(ft * 1.3 + i) * (r + 5)
            fy = y + r * 0.5 + (ft * 20 + i * 3) % (r * 2)
            fz = z + math.cos(ft * 1.1 + i * 0.8) * (r + 5)
            life = 1.0 - ((ft * 20 + i * 3) % (r * 2)) / (r * 2)
            glColor4f(1.0, 0.4 * life + 0.3, 0.05, life * 0.8)
            glVertex3f(fx, fy, fz)
        glEnd()
        glEnable(GL_DEPTH_TEST)

        # --- Weak spot (compiled sphere, scaled) ---
        wp = skull.weakspot_pos()
        pulse = 0.8 + 0.2 * math.sin(fire_t * 5 + skull.fire_phase)
        glColor4f(1.0 * pulse, 0.2 * pulse, 0.2 * pulse, 0.9)
        glPushMatrix()
        glTranslatef(wp[0], wp[1], wp[2])
        glScalef(wr, wr, wr)
        if sphere_dl:
            glCallList(sphere_dl)
        glPopMatrix()

        # --- HP bar above skull ---
        if skull.hp < skull.max_hp:
            hp_frac = max(0, skull.hp / skull.max_hp)
            bar_w = r * 2
            bar_y_pos = y + r + 15
            glDisable(GL_DEPTH_TEST)
            glLineWidth(4.0)
            glColor4f(0.3, 0.0, 0.0, 0.7)
            glBegin(GL_LINES)
            glVertex3f(x - bar_w/2, bar_y_pos, z)
            glVertex3f(x + bar_w/2, bar_y_pos, z)
            glEnd()
            r_col = 1.0 - hp_frac
            g_col = hp_frac
            glColor4f(r_col, g_col, 0.0, 0.9)
            glBegin(GL_LINES)
            glVertex3f(x - bar_w/2, bar_y_pos, z)
            glVertex3f(x - bar_w/2 + bar_w * hp_frac, bar_y_pos, z)
            glEnd()
            glEnable(GL_DEPTH_TEST)


def _draw_damage_numbers(skull):
    """Placeholder - damage numbers rendered in 2D pass."""
    pass


def _draw_skull_sphere(x, y, z, r, color_r, color_g, color_b, alpha, segments=10, rings=6):
    """Draw a simple sphere at position with given color and alpha."""
    glPushMatrix()
    glTranslatef(x, y, z)
    for i in range(rings):
        lat0 = math.pi * (-0.5 + i / rings)
        lat1 = math.pi * (-0.5 + (i + 1) / rings)
        y0 = math.sin(lat0) * r
        y1 = math.sin(lat1) * r
        r0 = math.cos(lat0) * r
        r1 = math.cos(lat1) * r
        glBegin(GL_QUAD_STRIP)
        for j in range(segments + 1):
            lng = 2 * math.pi * j / segments
            cx = math.cos(lng)
            cz = math.sin(lng)
            glColor4f(color_r, color_g, color_b, alpha)
            glVertex3f(cx * r0, y0, cz * r0)
            glVertex3f(cx * r1, y1, cz * r1)
        glEnd()
    glPopMatrix()


def _mirror_point(px, py, pz, player, fwd):
    """Mirror a world point across the player's forward plane.

    Reflects the forward component so behind becomes in-front,
    while preserving the lateral and vertical offset. This creates
    a 'see through the back of your head' effect.
    """
    # Vector from player to point
    dx = px - player.pos[0]
    dy = py - player.pos[1]
    dz = pz - player.pos[2]

    # Project onto forward axis
    dot = dx * fwd[0] + dy * fwd[1] + dz * fwd[2]

    # Negate the forward component (mirror across the plane perpendicular to fwd)
    mx = px - 2.0 * dot * fwd[0]
    my = py - 2.0 * dot * fwd[1]
    mz = pz - 2.0 * dot * fwd[2]

    return mx, my, mz


def _draw_holo_sphere(mx, my, mz, radius, alpha):
    """Draw a simple red holographic sphere at mirrored position."""
    glPushMatrix()
    glTranslatef(mx, my, mz)
    segments = 10
    rings = 6
    for i in range(rings):
        lat0 = math.pi * (-0.5 + i / rings)
        lat1 = math.pi * (-0.5 + (i + 1) / rings)
        y0 = math.sin(lat0) * radius
        y1 = math.sin(lat1) * radius
        r0_lat = math.cos(lat0) * radius
        r1_lat = math.cos(lat1) * radius
        glBegin(GL_QUAD_STRIP)
        for j in range(segments + 1):
            lng = 2 * math.pi * j / segments
            cx = math.cos(lng)
            cz = math.sin(lng)
            glColor4f(0.9, 0.1, 0.08, alpha)
            glVertex3f(cx * r0_lat, y0, cz * r0_lat)
            glVertex3f(cx * r1_lat, y1, cz * r1_lat)
        glEnd()
    glPopMatrix()


def _draw_holo_diamond(mx, my, mz, radius, alpha):
    """Draw a red holographic diamond shape at mirrored position."""
    glPushMatrix()
    glTranslatef(mx, my, mz)
    size = radius
    top = [0, size, 0]
    bottom = [0, -size, 0]
    eq = size * 0.7
    sides = [[eq, 0, 0], [0, 0, eq], [-eq, 0, 0], [0, 0, -eq]]
    glBegin(GL_TRIANGLES)
    for i in range(4):
        s1 = sides[i]
        s2 = sides[(i + 1) % 4]
        glColor4f(0.9, 0.1, 0.08, alpha)
        glVertex3f(top[0], top[1], top[2])
        glVertex3f(s1[0], s1[1], s1[2])
        glVertex3f(s2[0], s2[1], s2[2])
        glColor4f(0.7, 0.08, 0.06, alpha)
        glVertex3f(bottom[0], bottom[1], bottom[2])
        glVertex3f(s2[0], s2[1], s2[2])
        glVertex3f(s1[0], s1[1], s1[2])
    glEnd()
    glPopMatrix()


def _draw_holo_disc(mx, my, mz, radius, alpha):
    """Draw a red holographic flat disc at mirrored position."""
    glPushMatrix()
    glTranslatef(mx, my, mz)
    segments = 16
    thickness = radius * 0.2
    for face in [1, -1]:
        fy = face * thickness * 0.5
        glBegin(GL_TRIANGLE_FAN)
        glColor4f(0.9, 0.1, 0.08, alpha)
        glVertex3f(0, fy, 0)
        for i in range(segments + 1):
            a = (i / segments) * math.pi * 2
            glVertex3f(math.cos(a) * radius, fy, math.sin(a) * radius)
        glEnd()
    glBegin(GL_QUAD_STRIP)
    for i in range(segments + 1):
        a = (i / segments) * math.pi * 2
        cx, cz = math.cos(a) * radius, math.sin(a) * radius
        glColor4f(0.8, 0.1, 0.06, alpha)
        glVertex3f(cx, thickness * 0.5, cz)
        glVertex3f(cx, -thickness * 0.5, cz)
    glEnd()
    glPopMatrix()


def draw_entity_holograms(skulls, spawners, ammonites, player, sphere_dl=None, disc_dl=None):
    """Draw red holographic overlays for all entities outside the player's FOV.

    Mirrors entities across the player's forward plane so the player can
    'see behind themselves'.
    """
    fov_half = 45.0
    fov_cos = math.cos(math.radians(fov_half))
    fwd = player.get_look_dir()
    warn_radius = SKULL_WARN_RADIUS

    # Collect all entities that need holograms: (pos, radius, type, entity)
    holo_entities = []

    for skull in skulls:
        if not skull.alive:
            continue
        dx = skull.pos[0] - player.pos[0]
        dy = skull.pos[1] - player.pos[1]
        dz = skull.pos[2] - player.pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 1.0 or dist > warn_radius:
            continue
        dot_fwd = (fwd[0] * dx + fwd[1] * dy + fwd[2] * dz) / dist
        if dot_fwd > fov_cos:
            continue
        proximity = 1.0 - (dist / warn_radius)
        holo_entities.append(("skull", skull, dist, proximity))

    for sp in spawners:
        if not sp.alive:
            continue
        dx = sp.pos[0] - player.pos[0]
        dy = sp.pos[1] - player.pos[1]
        dz = sp.pos[2] - player.pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 1.0 or dist > warn_radius * 2:
            continue
        dot_fwd = (fwd[0] * dx + fwd[1] * dy + fwd[2] * dz) / dist
        if dot_fwd > fov_cos:
            continue
        proximity = 1.0 - (dist / (warn_radius * 2))
        holo_entities.append(("spawner", sp, dist, proximity))

    for am in ammonites:
        if not am.alive and not am.is_corpse:
            continue
        dx = am.pos[0] - player.pos[0]
        dy = am.pos[1] - player.pos[1]
        dz = am.pos[2] - player.pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 1.0 or dist > warn_radius:
            continue
        dot_fwd = (fwd[0] * dx + fwd[1] * dy + fwd[2] * dz) / dist
        if dot_fwd > fov_cos:
            continue
        proximity = 1.0 - (dist / warn_radius)
        holo_entities.append(("ammonite", am, dist, proximity))

    if not holo_entities:
        return

    glDisable(GL_DEPTH_TEST)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    for etype, entity, dist, proximity in holo_entities:
        alpha = 0.15 + proximity * 0.4
        mx, my, mz = _mirror_point(entity.pos[0], entity.pos[1], entity.pos[2], player, fwd)

        if etype == "skull":
            # Red sphere using compiled display list
            glColor4f(0.9, 0.1, 0.08, alpha)
            glPushMatrix()
            glTranslatef(mx, my, mz)
            glScalef(SKULL_RADIUS, SKULL_RADIUS, SKULL_RADIUS)
            glCallList(sphere_dl)
            glPopMatrix()

            # Fewer fire particles (5 instead of 20)
            r = SKULL_RADIUS
            skull = entity
            fire_t = g_frame_time
            glPointSize(4.0)
            glBegin(GL_POINTS)
            for i in range(5):
                phase = skull.fire_phase + i * 2.8
                ft = fire_t * 3 + phase
                fx_real = skull.pos[0] + math.sin(ft * 1.3 + i) * (r + 5)
                fy_real = skull.pos[1] + r * 0.5 + (ft * 20 + i * 3) % (r * 2)
                fz_real = skull.pos[2] + math.cos(ft * 1.1 + i * 0.8) * (r + 5)
                fx, fy, fz = _mirror_point(fx_real, fy_real, fz_real, player, fwd)
                life = 1.0 - ((ft * 20 + i * 3) % (r * 2)) / (r * 2)
                glColor4f(1.0, 0.15, 0.05, life * alpha * 0.6)
                glVertex3f(fx, fy, fz)
            glEnd()

        elif etype == "spawner":
            _draw_holo_diamond(mx, my, mz, SPAWNER_RADIUS * 1.5, alpha)

        elif etype == "ammonite":
            # Red disc using compiled display list
            glColor4f(0.9, 0.1, 0.08, alpha)
            glPushMatrix()
            glTranslatef(mx, my, mz)
            glScalef(AMMONITE_RADIUS, AMMONITE_RADIUS, AMMONITE_RADIUS)
            glCallList(disc_dl)
            glPopMatrix()

    glEnable(GL_DEPTH_TEST)


def draw_death_screen(screen):
    """Draw a red death overlay."""
    sw, sh = screen.get_size()
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    glOrtho(0, sw, sh, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    glDisable(GL_DEPTH_TEST)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    # Red overlay
    glColor4f(0.5, 0.0, 0.0, 0.6)
    glBegin(GL_QUADS)
    glVertex2f(0, 0)
    glVertex2f(sw, 0)
    glVertex2f(sw, sh)
    glVertex2f(0, sh)
    glEnd()

    # "YOU DIED" text
    font = pygame.font.SysFont("consolas", 48, bold=True)
    surf = font.render("YOU DIED", True, (255, 50, 50))
    data = pygame.image.tostring(surf, "RGBA", True)
    tw, th = surf.get_size()
    glRasterPos2f((sw - tw) // 2, sh // 2 + th // 2)
    glDrawPixels(tw, th, GL_RGBA, GL_UNSIGNED_BYTE, data)

    # Subtitle
    font2 = pygame.font.SysFont("consolas", 18)
    surf2 = font2.render("Respawning...", True, (200, 150, 150))
    data2 = pygame.image.tostring(surf2, "RGBA", True)
    tw2, th2 = surf2.get_size()
    glRasterPos2f((sw - tw2) // 2, sh // 2 + th // 2 + th2 + 20)
    glDrawPixels(tw2, th2, GL_RGBA, GL_UNSIGNED_BYTE, data2)

    glDisable(GL_BLEND)
    glEnable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)
    glPopMatrix()


def draw_damage_numbers_2d(screen, entities, player):
    """Draw damage numbers as 2D text overlay (projected from 3D positions).

    entities: list of objects with .damage_numbers attribute (skulls, spawners, etc.)
    """
    sw, sh = screen.get_size()

    modelview = glGetDoublev(GL_MODELVIEW_MATRIX)
    projection = glGetDoublev(GL_PROJECTION_MATRIX)
    viewport = glGetIntegerv(GL_VIEWPORT)

    has_numbers = any(e.damage_numbers for e in entities)
    if not has_numbers:
        return

    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    glOrtho(0, sw, 0, sh, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    glDisable(GL_DEPTH_TEST)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    font = pygame.font.SysFont("consolas", 13, bold=True)

    for entity in entities:
        for dn in entity.damage_numbers:
            text, wx, wy, wz, timer, color = dn
            alpha = min(1.0, timer * 3)
            if alpha <= 0:
                continue

            try:
                sx, sy, sz = gluProject(wx, wy, wz, modelview, projection, viewport)
            except Exception:
                continue

            if sz < 0 or sz > 1:
                continue

            r, g, b = color
            surf = font.render(text, True, (int(r*255*alpha), int(g*255*alpha), int(b*255*alpha)))
            data = pygame.image.tostring(surf, "RGBA", True)
            tw, th = surf.get_size()

            glRasterPos2f(sx - tw // 2, sy + 5)
            glDrawPixels(tw, th, GL_RGBA, GL_UNSIGNED_BYTE, data)

    glDisable(GL_BLEND)
    glEnable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)
    glPopMatrix()


def draw_bhop_indicator(screen, player):
    """Draw a bhop timing bar at bottom-center of screen."""
    sw, sh = screen.get_size()
    now = time.time()

    # Check if we should show anything
    show_bar = player.bhop_bar_active and player.last_land_time > 0
    show_feedback = player.bhop_feedback_timer > 0

    if not show_bar and not show_feedback:
        return

    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    glOrtho(0, sw, sh, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    glDisable(GL_DEPTH_TEST)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    bar_w = 300
    bar_h = 16
    bar_x = (sw - bar_w) // 2
    bar_y = sh - 80

    if show_bar:
        elapsed = now - player.last_land_time
        fill_frac = min(elapsed / (BHOP_WINDOW * 1.2), 1.0)  # slight overshoot visible

        # Background
        glColor4f(0.0, 0.0, 0.0, 0.6)
        glBegin(GL_QUADS)
        glVertex2f(bar_x - 2, bar_y - 2)
        glVertex2f(bar_x + bar_w + 2, bar_y - 2)
        glVertex2f(bar_x + bar_w + 2, bar_y + bar_h + 2)
        glVertex2f(bar_x - 2, bar_y + bar_h + 2)
        glEnd()

        # Perfect zone (green)
        perfect_w = (BHOP_PERFECT_WINDOW / (BHOP_WINDOW * 1.2)) * bar_w
        glColor4f(0.2, 0.9, 0.3, 0.5)
        glBegin(GL_QUADS)
        glVertex2f(bar_x, bar_y)
        glVertex2f(bar_x + perfect_w, bar_y)
        glVertex2f(bar_x + perfect_w, bar_y + bar_h)
        glVertex2f(bar_x, bar_y + bar_h)
        glEnd()

        # Good zone (yellow)
        good_w = (BHOP_WINDOW / (BHOP_WINDOW * 1.2)) * bar_w
        glColor4f(0.9, 0.8, 0.2, 0.35)
        glBegin(GL_QUADS)
        glVertex2f(bar_x + perfect_w, bar_y)
        glVertex2f(bar_x + good_w, bar_y)
        glVertex2f(bar_x + good_w, bar_y + bar_h)
        glVertex2f(bar_x + perfect_w, bar_y + bar_h)
        glEnd()

        # Miss zone (red, past the window)
        glColor4f(0.7, 0.15, 0.15, 0.3)
        glBegin(GL_QUADS)
        glVertex2f(bar_x + good_w, bar_y)
        glVertex2f(bar_x + bar_w, bar_y)
        glVertex2f(bar_x + bar_w, bar_y + bar_h)
        glVertex2f(bar_x + good_w, bar_y + bar_h)
        glEnd()

        # Moving cursor (white line showing current time)
        cursor_x = bar_x + fill_frac * bar_w
        glColor4f(1.0, 1.0, 1.0, 0.9)
        glLineWidth(3.0)
        glBegin(GL_LINES)
        glVertex2f(cursor_x, bar_y - 4)
        glVertex2f(cursor_x, bar_y + bar_h + 4)
        glEnd()

        # Zone labels
        font = pygame.font.SysFont("consolas", 11)
        for label, lx in [("PERFECT", bar_x + perfect_w * 0.5),
                           ("GOOD", bar_x + perfect_w + (good_w - perfect_w) * 0.5),
                           ("MISS", bar_x + good_w + (bar_w - good_w) * 0.5)]:
            surf = font.render(label, True, (200, 200, 200))
            data = pygame.image.tostring(surf, "RGBA", True)
            lw, lh = surf.get_size()
            glRasterPos2f(lx - lw // 2, bar_y + bar_h + lh + 4)
            glDrawPixels(lw, lh, GL_RGBA, GL_UNSIGNED_BYTE, data)

    # Feedback text
    if show_feedback:
        alpha = min(1.0, player.bhop_feedback_timer / 0.5)
        colors = {
            "PERFECT": (0.3, 1.0, 0.4),
            "GOOD": (1.0, 0.9, 0.3),
            "MISS": (1.0, 0.3, 0.3),
        }
        r, g, b = colors.get(player.bhop_feedback, (1, 1, 1))
        font = pygame.font.SysFont("consolas", 22, bold=True)
        timing_ms = player.bhop_feedback_timing * 1000
        text = f"{player.bhop_feedback}  ({timing_ms:.0f}ms)"
        surf = font.render(text, True, (int(r*255), int(g*255), int(b*255)))
        data = pygame.image.tostring(surf, "RGBA", True)
        tw, th = surf.get_size()

        # Position above the bar
        tx = (sw - tw) // 2
        ty = bar_y - 10

        glColor4f(0, 0, 0, 0.5 * alpha)
        glBegin(GL_QUADS)
        glVertex2f(tx - 4, ty - th - 4)
        glVertex2f(tx + tw + 4, ty - th - 4)
        glVertex2f(tx + tw + 4, ty + 4)
        glVertex2f(tx - 4, ty + 4)
        glEnd()

        glRasterPos2f(tx, ty)
        glDrawPixels(tw, th, GL_RGBA, GL_UNSIGNED_BYTE, data)

    glDisable(GL_BLEND)
    glEnable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)
    glPopMatrix()


# =============================================================================
# Rendering
# =============================================================================

def draw_ground():
    """Draw a large checkered ground plane."""
    GRID_SIZE = 200
    TILE_SIZE = 100.0
    HALF = GRID_SIZE * TILE_SIZE / 2

    glBegin(GL_QUADS)
    for x in range(GRID_SIZE):
        for z in range(GRID_SIZE):
            wx = x * TILE_SIZE - HALF
            wz = z * TILE_SIZE - HALF
            if (x + z) % 2 == 0:
                glColor3f(0.15, 0.15, 0.18)
            else:
                glColor3f(0.22, 0.22, 0.28)
            glVertex3f(wx, 0, wz)
            glVertex3f(wx + TILE_SIZE, 0, wz)
            glVertex3f(wx + TILE_SIZE, 0, wz + TILE_SIZE)
            glVertex3f(wx, 0, wz + TILE_SIZE)
    glEnd()


def draw_ground_compiled():
    """Create a display list for the ground (much faster)."""
    dl = glGenLists(1)
    glNewList(dl, GL_COMPILE)
    draw_ground()
    glEndList()
    return dl


def draw_pillars():
    """Draw some vertical pillars as landmarks."""
    pillar_positions = []
    for i in range(-5, 6):
        for j in range(-5, 6):
            if (i + j) % 3 == 0 and (i != 0 or j != 0):
                pillar_positions.append((i * 500.0, j * 500.0))

    for px, pz in pillar_positions:
        h = 200.0 + abs(px + pz) * 0.1
        w = 15.0
        # Pillar color based on position
        r = 0.3 + 0.2 * math.sin(px * 0.01)
        g = 0.1 + 0.1 * math.cos(pz * 0.01)
        b = 0.4 + 0.2 * math.sin((px + pz) * 0.005)
        glColor3f(r, g, b)

        glBegin(GL_QUADS)
        # Front
        glVertex3f(px - w, 0, pz + w)
        glVertex3f(px + w, 0, pz + w)
        glVertex3f(px + w, h, pz + w)
        glVertex3f(px - w, h, pz + w)
        # Back
        glVertex3f(px - w, 0, pz - w)
        glVertex3f(px + w, 0, pz - w)
        glVertex3f(px + w, h, pz - w)
        glVertex3f(px - w, h, pz - w)
        # Left
        glVertex3f(px - w, 0, pz - w)
        glVertex3f(px - w, 0, pz + w)
        glVertex3f(px - w, h, pz + w)
        glVertex3f(px - w, h, pz - w)
        # Right
        glVertex3f(px + w, 0, pz - w)
        glVertex3f(px + w, 0, pz + w)
        glVertex3f(px + w, h, pz + w)
        glVertex3f(px + w, h, pz - w)
        # Top
        glColor3f(r + 0.2, g + 0.2, b + 0.2)
        glVertex3f(px - w, h, pz - w)
        glVertex3f(px + w, h, pz - w)
        glVertex3f(px + w, h, pz + w)
        glVertex3f(px - w, h, pz + w)
        glEnd()


def draw_pillar_list():
    dl = glGenLists(1)
    glNewList(dl, GL_COMPILE)
    draw_pillars()
    glEndList()
    return dl


# Pre-computed trig tables for unit sphere
_SPHERE_SEGS = 8
_SPHERE_RINGS = 6
_sphere_cos_lng = [math.cos(2 * math.pi * j / _SPHERE_SEGS) for j in range(_SPHERE_SEGS + 1)]
_sphere_sin_lng = [math.sin(2 * math.pi * j / _SPHERE_SEGS) for j in range(_SPHERE_SEGS + 1)]
_sphere_lat_data = []
for _i in range(_SPHERE_RINGS):
    _lat0 = math.pi * (-0.5 + _i / _SPHERE_RINGS)
    _lat1 = math.pi * (-0.5 + (_i + 1) / _SPHERE_RINGS)
    _sphere_lat_data.append((math.sin(_lat0), math.sin(_lat1), math.cos(_lat0), math.cos(_lat1)))

# Pre-computed trig for disc (ammonite)
_DISC_SEGS = 12
_disc_cos = [math.cos((i / _DISC_SEGS) * math.pi * 2) for i in range(_DISC_SEGS + 1)]
_disc_sin = [math.sin((i / _DISC_SEGS) * math.pi * 2) for i in range(_DISC_SEGS + 1)]

# Pre-computed spiral for ammonite
_SPIRAL_POINTS = 30
_SPIRAL_TURNS = 3.5
_spiral_data = []
for _i in range(_SPIRAL_POINTS):
    _t = _i / (_SPIRAL_POINTS - 1)
    _a = _t * _SPIRAL_TURNS * math.pi * 2
    _spiral_data.append((_t, math.cos(_a), math.sin(_a)))


def compile_unit_sphere():
    """Compile a white unit sphere (radius=1) display list."""
    dl = glGenLists(1)
    glNewList(dl, GL_COMPILE)
    for sy0, sy1, sr0, sr1 in _sphere_lat_data:
        glBegin(GL_QUAD_STRIP)
        for j in range(_SPHERE_SEGS + 1):
            cx = _sphere_cos_lng[j]
            cz = _sphere_sin_lng[j]
            glVertex3f(cx * sr0, sy0, cz * sr0)
            glVertex3f(cx * sr1, sy1, cz * sr1)
        glEnd()
    glEndList()
    return dl


def compile_unit_disc():
    """Compile a unit disc (radius=1, thickness=0.25) display list."""
    dl = glGenLists(1)
    glNewList(dl, GL_COMPILE)
    thickness = 0.25
    # Top and bottom faces
    for face in [1, -1]:
        fy = face * thickness * 0.5
        glBegin(GL_TRIANGLE_FAN)
        glVertex3f(0, fy, 0)
        for i in range(_DISC_SEGS + 1):
            glVertex3f(_disc_cos[i], fy, _disc_sin[i])
        glEnd()
    # Rim
    glBegin(GL_QUAD_STRIP)
    for i in range(_DISC_SEGS + 1):
        glVertex3f(_disc_cos[i], thickness * 0.5, _disc_sin[i])
        glVertex3f(_disc_cos[i], -thickness * 0.5, _disc_sin[i])
    glEnd()
    glEndList()
    return dl


# Global frame time (set once per frame)
g_frame_time = 0.0


def draw_crosshair(screen_w, screen_h):
    """Draw a simple crosshair."""
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    glOrtho(0, screen_w, screen_h, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()

    glDisable(GL_DEPTH_TEST)
    cx, cy = screen_w // 2, screen_h // 2
    size = 12
    gap = 3

    glLineWidth(2.0)
    glColor4f(1.0, 1.0, 1.0, 0.8)
    glBegin(GL_LINES)
    glVertex2f(cx - size, cy); glVertex2f(cx - gap, cy)
    glVertex2f(cx + gap, cy); glVertex2f(cx + size, cy)
    glVertex2f(cx, cy - size); glVertex2f(cx, cy - gap)
    glVertex2f(cx, cy + gap); glVertex2f(cx, cy + size)
    glEnd()

    glEnable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)
    glPopMatrix()


def draw_hud(screen, player, fps, show_hud):
    """Draw HUD text overlay using pygame."""
    if not show_hud:
        return

    font = pygame.font.SysFont("consolas", 16)
    dash_cd = f"Dash: READY" if player.dash_cooldown_timer <= 0 else f"Dash: {player.dash_cooldown_timer:.1f}s"
    state_label = player.state + (" (crouched)" if player.crouching else "")
    lines = [
        f"State: {state_label}",
        f"Speed: {player.speed:.0f} u/s",
        f"Vel: ({player.vel[0]:.0f}, {player.vel[1]:.0f}, {player.vel[2]:.0f})",
        f"Pos: ({player.pos[0]:.0f}, {player.pos[1]:.0f}, {player.pos[2]:.0f})",
        f"HP: {player.hp} | {dash_cd} | FPS: {fps:.0f}",
        "",
        "WASD: Move | Space: Jump/Dash/Slide/Stomp",
        "Mouse: Look | ESC: Quit | F1: Toggle HUD | TAB: Reset",
    ]

    # State color
    state_colors = {
        STATE_GROUND: (100, 255, 100),
        STATE_AIRBORNE: (100, 200, 255),
        STATE_DASHING: (255, 200, 50),
        STATE_SLIDING: (255, 100, 255),
        STATE_STOMPING: (255, 80, 80),
    }

    # Speed bar
    bar_width = 200
    bar_height = 8
    speed_frac = min(player.speed / 2000.0, 1.0)

    # Create a surface with per-pixel alpha
    overlay = pygame.Surface((320, len(lines) * 20 + 40), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 120))

    for i, line in enumerate(lines):
        color = state_colors.get(player.state, (255, 255, 255)) if i == 0 else (220, 220, 220)
        text = font.render(line, True, color)
        overlay.blit(text, (10, 5 + i * 20))

    # Speed bar
    bar_y = len(lines) * 20 + 10
    pygame.draw.rect(overlay, (60, 60, 60), (10, bar_y, bar_width, bar_height))
    bar_color = (100, 255, 100) if speed_frac < 0.5 else (255, 255, 50) if speed_frac < 0.8 else (255, 80, 80)
    pygame.draw.rect(overlay, bar_color, (10, bar_y, int(bar_width * speed_frac), bar_height))

    # Blit overlay onto screen via texture
    text_data = pygame.image.tostring(overlay, "RGBA", True)
    w, h = overlay.get_size()

    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    sw, sh = screen.get_size()
    glOrtho(0, sw, 0, sh, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()

    glDisable(GL_DEPTH_TEST)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    glRasterPos2i(10, sh - 10)
    glDrawPixels(w, h, GL_RGBA, GL_UNSIGNED_BYTE, text_data)

    glDisable(GL_BLEND)
    glEnable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)
    glPopMatrix()


# =============================================================================
# Main
# =============================================================================

def generate_bhop_sound():
    """Generate a subtle, satisfying ASMR tick/click sound for perfect bhops."""
    sample_rate = 44100
    duration = 0.08  # short, crisp
    n_samples = int(sample_rate * duration)
    samples = array.array("h")  # signed 16-bit

    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 60)  # sharp attack, fast decay
        # Layered tones: soft click + subtle high shimmer
        click = math.sin(2 * math.pi * 1800 * t) * 0.5
        shimmer = math.sin(2 * math.pi * 4200 * t) * 0.25
        sub = math.sin(2 * math.pi * 400 * t) * 0.25
        sample = int(env * (click + shimmer + sub) * 12000)
        sample = max(-32768, min(32767, sample))
        samples.append(sample)

    sound = pygame.mixer.Sound(buffer=samples)
    sound.set_volume(0.35)
    return sound


def generate_land_sound():
    """Generate a low-pitched, soft ASMR thud for landing (bhop window start)."""
    sample_rate = 44100
    duration = 0.12
    n_samples = int(sample_rate * duration)
    samples = array.array("h")

    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 25)  # smooth decay
        # Deep, soft thud: low sine + sub-bass rumble
        low = math.sin(2 * math.pi * 120 * t) * 0.5
        sub = math.sin(2 * math.pi * 60 * t) * 0.35
        tap = math.sin(2 * math.pi * 250 * t) * math.exp(-t * 50) * 0.15
        sample = int(env * (low + sub + tap) * 10000)
        sample = max(-32768, min(32767, sample))
        samples.append(sample)

    sound = pygame.mixer.Sound(buffer=samples)
    sound.set_volume(0.3)
    return sound


def generate_shotgun_sound():
    """Generate a punchy shotgun blast sound."""
    sample_rate = 44100
    duration = 0.15
    n_samples = int(sample_rate * duration)
    samples = array.array("h")

    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 30)
        # White noise burst + low thump
        noise = random.uniform(-1, 1) * 0.6
        thump = math.sin(2 * math.pi * 80 * t) * 0.4
        crack = math.sin(2 * math.pi * 600 * t) * math.exp(-t * 80) * 0.3
        sample = int(env * (noise + thump + crack) * 16000)
        sample = max(-32768, min(32767, sample))
        samples.append(sample)

    sound = pygame.mixer.Sound(buffer=samples)
    sound.set_volume(0.4)
    return sound


def generate_ammonite_pickup_sounds(count=8):
    """Generate a series of corpse pickup sounds at increasing pitches for combos."""
    sounds = []
    sample_rate = 44100
    duration = 0.12
    n_samples = int(sample_rate * duration)
    for level in range(count):
        # Base freq rises with combo level
        base_freq = 500 + level * 200
        samples = array.array("h")
        for i in range(n_samples):
            t = i / sample_rate
            env = math.exp(-t * 35)
            # Bright chime: main tone + octave + shimmer
            tone = math.sin(2 * math.pi * base_freq * t) * 0.45
            octave = math.sin(2 * math.pi * base_freq * 2 * t) * 0.3
            shimmer = math.sin(2 * math.pi * base_freq * 3.5 * t) * math.exp(-t * 60) * 0.2
            thud = math.sin(2 * math.pi * 150 * t) * math.exp(-t * 50) * 0.15
            sample = int(env * (tone + octave + shimmer + thud) * 14000)
            sample = max(-32768, min(32767, sample))
            samples.append(sample)
        sound = pygame.mixer.Sound(buffer=samples)
        sound.set_volume(0.45)
        sounds.append(sound)
    return sounds


def main():
    pygame.init()
    pygame.font.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)

    bhop_sound = generate_bhop_sound()
    land_sound = generate_land_sound()
    shotgun_sound = generate_shotgun_sound()
    ammonite_pickup_sounds = generate_ammonite_pickup_sounds()

    screen_w, screen_h = 1280, 720
    screen = pygame.display.set_mode((screen_w, screen_h), DOUBLEBUF | OPENGL | RESIZABLE)
    pygame.display.set_caption("Hyperdemon Movement Demo")

    # OpenGL setup
    glEnable(GL_DEPTH_TEST)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glClearColor(0.05, 0.02, 0.08, 1.0)

    # Fog for atmosphere
    glEnable(GL_FOG)
    glFogi(GL_FOG_MODE, GL_LINEAR)
    glFogfv(GL_FOG_COLOR, (0.05, 0.02, 0.08, 1.0))
    glFogf(GL_FOG_START, 2000.0)
    glFogf(GL_FOG_END, 8000.0)

    # Perspective
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(90, screen_w / screen_h, 1.0, 15000.0)
    glMatrixMode(GL_MODELVIEW)

    # Compile display lists
    ground_dl = draw_ground_compiled()
    pillar_dl = draw_pillar_list()
    sphere_dl = compile_unit_sphere()
    disc_dl = compile_unit_disc()

    # Player
    player = Player()

    # Enemies
    skulls = []
    spawners = create_spawners(player.pos)
    spawner_new_timer = 0.0
    ammonites = create_ammonites(player.pos)

    # Mouse capture
    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)

    clock = pygame.time.Clock()
    show_hud = True
    fps = 60.0

    running = True
    while running:
        dt = clock.tick(240) / 1000.0
        dt = min(dt, 0.05)  # clamp to avoid physics explosions
        dt *= GAME_SPEED  # global time scale
        fps = clock.get_fps()

        # Reset per-frame flags
        player.space_just_pressed = False

        # Events
        for event in pygame.event.get():
            if event.type == QUIT:
                running = False
            elif event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    running = False
                elif event.key == K_F1:
                    show_hud = not show_hud
                elif event.key == K_TAB:
                    player.pos = [0.0, PLAYER_HEIGHT, 0.0]
                    player.vel = [0.0, 0.0, 0.0]
                    player.state = STATE_GROUND
                    player.current_height = PLAYER_HEIGHT
                    player.has_dashed = False
                elif event.key == K_BACKSPACE:
                    # Full reset: respawn player and reset all enemies
                    player.alive = True
                    player.hp = PLAYER_MAX_HP
                    player.pos = [0.0, PLAYER_HEIGHT, 0.0]
                    player.vel = [0.0, 0.0, 0.0]
                    player.state = STATE_GROUND
                    player.current_height = PLAYER_HEIGHT
                    player.has_dashed = False
                    player.dash_cooldown_timer = 0.0
                    player.pellets = []
                    skulls = []
                    spawners = create_spawners(player.pos)
                    spawner_new_timer = 0.0
                    ammonites = create_ammonites(player.pos)
                elif event.key == K_SPACE:
                    player.space_just_pressed = True
                    player.space_held = True
                    player.prev_space_press_time = player.last_space_press_time
                    player.last_space_press_time = time.time()
            elif event.type == KEYUP:
                if event.key == K_SPACE:
                    player.space_held = False
            elif event.type == MOUSEBUTTONDOWN:
                if event.button == 1 and player.shotgun_cooldown <= 0:
                    fire_shotgun(player)
                    player.shotgun_cooldown = SHOTGUN_COOLDOWN
                    shotgun_sound.play()
            elif event.type == MOUSEMOTION:
                dx, dy = event.rel
                player.yaw += dx * MOUSE_SENSITIVITY
                player.pitch -= dy * MOUSE_SENSITIVITY
                player.pitch = max(-89.0, min(89.0, player.pitch))
            elif event.type == VIDEORESIZE:
                screen_w, screen_h = event.w, event.h
                screen = pygame.display.set_mode(
                    (screen_w, screen_h), DOUBLEBUF | OPENGL | RESIZABLE
                )
                glViewport(0, 0, screen_w, screen_h)
                glMatrixMode(GL_PROJECTION)
                glLoadIdentity()
                gluPerspective(90, screen_w / screen_h, 1.0, 15000.0)
                glMatrixMode(GL_MODELVIEW)

        # Cache frame time once
        global g_frame_time
        g_frame_time = time.time()

        # Input
        keys = pygame.key.get_pressed()

        # Death screen — stay dead until backspace
        if not player.alive:
            pass  # enemies frozen, wait for backspace reset
        else:
            # Update physics
            update_player(player, keys, dt)
            update_pellets(player, dt)
            check_pellet_hits(player, skulls)
            check_pellet_hits_spawners(player, spawners)
            check_pellet_hits_ammonites(player, ammonites)
            skulls = update_skulls(skulls, player, dt)
            spawners = update_spawners(spawners, skulls, player, dt)
            ammonites = update_ammonites(ammonites, player, dt, ammonite_pickup_sounds)

            # Spawn new ammonite groups periodically
            if len([a for a in ammonites if a.alive or a.is_corpse]) < AMMONITE_MAX:
                if random.random() < 0.005:  # ~every few seconds
                    angle = random.uniform(0, math.pi * 2)
                    dist = random.uniform(AMMONITE_MIN_DIST, AMMONITE_SPAWN_RANGE)
                    cx = player.pos[0] + math.cos(angle) * dist
                    cz = player.pos[2] + math.sin(angle) * dist
                    ammonites.extend(_spawn_ammonite_group(cx, cz))

            # Spawn new spawners periodically
            spawner_new_timer += dt
            if spawner_new_timer >= SPAWNER_NEW_INTERVAL and len([s for s in spawners if s.alive]) < SPAWNER_MAX:
                spawner_new_timer = 0.0
                angle = random.uniform(0, math.pi * 2)
                dist = random.uniform(SPAWNER_MIN_DIST, SPAWNER_SPAWN_RANGE)
                spawners.append(Spawner(
                    player.pos[0] + math.cos(angle) * dist,
                    player.pos[2] + math.sin(angle) * dist,
                ))

        # Play bhop sound on perfect timing
        if player.just_landed:
            land_sound.play()
        if player.bhop_hit:
            bhop_sound.play()

        # Camera
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        look_dir = player.get_look_dir()
        eye = player.pos
        target = [eye[0] + look_dir[0], eye[1] + look_dir[1], eye[2] + look_dir[2]]
        gluLookAt(
            eye[0], eye[1], eye[2],
            target[0], target[1], target[2],
            0, 1, 0,
        )

        # Draw world
        glCallList(ground_dl)
        glCallList(pillar_dl)

        # Draw spawners
        draw_spawners(spawners, sphere_dl)

        # Draw enemies
        draw_skulls(skulls, sphere_dl)
        draw_ammonites(ammonites, disc_dl)

        # Draw red holograms for all entities outside FOV
        draw_entity_holograms(skulls, spawners, ammonites, player, sphere_dl, disc_dl)

        # Draw pellets
        draw_pellets(player)

        # Draw crosshair
        draw_crosshair(screen_w, screen_h)

        # Draw HUD
        draw_hud(screen, player, fps, show_hud)
        draw_bhop_indicator(screen, player)
        draw_damage_numbers_2d(screen, skulls + spawners + ammonites, player)

        # Death screen overlay
        if not player.alive:
            draw_death_screen(screen)

        pygame.display.flip()

    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
