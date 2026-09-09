import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Grid, OrbitControls, useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { apiUrl } from '../config'

export type PartMode = 'both' | 'male' | 'female'
export type ViewMode = 'assembled' | 'exploded'

export interface ViewerProps {
  url: string | null
  partMode: PartMode
  viewMode: ViewMode
  showMale: boolean
  showFemale: boolean
  stale: boolean
  resetToken: number
}

/**
 * The GLB is authoritative. Its `male` and `female` nodes are used directly -
 * nothing about the mold is recomputed in JavaScript, and no second
 * approximation of the tray exists in the browser.
 *
 * The model is authored Z-up in millimetres (origin at the plan centre on the
 * parting plane, +Z the plug direction), and the exporter puts the Z-up to Y-up
 * conversion on the assembly's root node, so the loaded scene is already
 * oriented and this file adds no rotation of its own. The camera is fitted to
 * the real bounding box, so a 235 mm plate frames like a 500 mm one.
 */
/** Which named GLB nodes are visible, given the controls. Pure, so the rule is
 *  testable without a WebGL context. */
export function partVisibility(
  partMode: PartMode,
  showMale: boolean,
  showFemale: boolean,
): { male: boolean; female: boolean } {
  return {
    male: (partMode === 'both' || partMode === 'male') && showMale,
    female: (partMode === 'both' || partMode === 'female') && showFemale,
  }
}

/** Separation along the press axis, in millimetres. */
export function explodeOffset(viewMode: ViewMode): number {
  return viewMode === 'exploded' ? 60 : 0
}

function MoldScene({ url, partMode, viewMode, showMale, showFemale, onMeasured }: Omit<ViewerProps, 'stale' | 'resetToken'> & { url: string; onMeasured: (m: { radius: number; floorY: number }) => void }) {
  const { scene } = useGLTF(apiUrl(url))
  const cloned = useMemo(() => scene.clone(true), [scene])
  const { camera, controls } = useThree() as any

  const parts = useMemo(() => {
    const found: Record<string, THREE.Object3D> = {}
    cloned.traverse((child) => {
      if (child.name === 'male' || child.name === 'female') found[child.name] = child
    })
    return found
  }, [cloned])

  const explode = explodeOffset(viewMode)
  useEffect(() => {
    const wanted = partVisibility(partMode, showMale, showFemale)
    for (const [name, object] of Object.entries(parts)) {
      object.visible = wanted[name as 'male' | 'female']
      object.position.set(0, 0, name === 'female' ? explode : -explode)
    }
  }, [parts, partMode, showMale, showFemale, explode])

  // Re-measured after the parts move, not just when the model loads: exploding
  // drops the male half well below where it sits assembled, and a floor placed
  // from the assembled box would then cut straight through it.
  useEffect(() => {
    const box = new THREE.Box3().setFromObject(cloned)
    if (box.isEmpty()) return
    onMeasured({
      radius: box.getBoundingSphere(new THREE.Sphere()).radius,
      floorY: box.min.y,
    })
  }, [cloned, explode, partMode, showMale, showFemale, onMeasured])

  useEffect(() => {
    const box = new THREE.Box3().setFromObject(cloned)
    if (box.isEmpty()) return
    const centre = box.getCenter(new THREE.Vector3())
    const sphere = box.getBoundingSphere(new THREE.Sphere())
    const limits = cameraLimits(sphere.radius, (camera as THREE.PerspectiveCamera).fov)
    // Plain world coordinates: the box already reflects the GLB's own Y-up
    // rotation, so there is nothing left to convert here.
    camera.position.set(
      centre.x + limits.distance * 0.62,
      centre.y + limits.distance * 0.55,
      centre.z + limits.distance * 0.62,
    )
    camera.near = limits.near
    camera.far = limits.far
    camera.updateProjectionMatrix()
    if (controls) {
      controls.target.copy(centre)
      controls.update()
    }
  }, [cloned, camera, controls])

  // No rotation here. CadQuery's glTF exporter already writes the Z-up to Y-up
  // conversion onto the assembly's root node (a -90 degree quaternion about X),
  // so rotating again turned the whole 180 degrees and stood the plate on its
  // edge. The mesh data stays Z-up, which is why the explode offset above is
  // still along the parts' local Z - that is the press axis.
  return <primitive object={cloned} />
}

/**
 * A light that rides the camera, aimed at the origin.
 *
 * A fixed rig can only light the sides it faces. Every light here used to be
 * above the parting plane, and a hemisphere light gives down-facing surfaces its
 * ground colour and nothing else - so looking up at an exploded mold showed a
 * black silhouette. A headlight makes the guarantee positional rather than
 * directional: whatever you have turned towards you is lit, from any angle. The
 * fixed key and fill still do the shaping; this only sets the floor.
 */
function CameraLight({ intensity }: { intensity: number }) {
  const light = useRef<THREE.DirectionalLight>(null)
  useFrame(({ camera }) => {
    light.current?.position.copy(camera.position)
  })
  return <directionalLight ref={light} intensity={intensity} />
}

/**
 * Clipping planes and zoom stops, from the model's bounding sphere.
 *
 * `near` must follow the model's *size*, never the camera's starting distance.
 * Deriving it from the start distance looks right until someone zooms: the plane
 * stays where it was, and everything nearer than it is sliced away, so the mold
 * appears cut open. The zoom stops then keep the camera from ever reaching the
 * plane - `minDistance` leaves the nearest surface hundreds of times further out
 * than `near` even head-on.
 *
 * The near/far ratio lands at 20000, which is three.js's own default spread and
 * ample for a 24-bit depth buffer. Depth precision was never what made the grid
 * shimmer - drawing an infinite grid out to the fade distance was - so there is
 * nothing to buy back by squeezing it.
 *
 * Pure, so the rule is testable without a WebGL context.
 */
export function cameraLimits(radius: number, fovDegrees: number) {
  const r = Math.max(radius, 1)
  const fov = (fovDegrees * Math.PI) / 180
  return {
    distance: r / Math.sin(fov / 2),
    near: r / 500,
    far: r * 40,
    minDistance: r * 0.5,
    maxDistance: r * 20,
  }
}

/** Grid spacing that suits the model rather than the scene's units: a 60 mm tray
 *  and a 500 mm one should both get a readable number of squares. */
export function gridSpacing(radius: number): { cell: number; section: number; extent: number } {
  const target = Math.max(radius, 1) / 12
  const steps = [1, 2, 5, 10, 20, 25, 50, 100]
  const cell = steps.find((s) => s >= target) ?? 100
  return { cell, section: cell * 5, extent: Math.max(radius, 1) * 4 }
}

export function Viewer(props: ViewerProps) {
  const [key, setKey] = useState(0)
  const [measured, setMeasured] = useState({ radius: 150, floorY: -20 })
  useEffect(() => setKey((k) => k + 1), [props.resetToken])
  const { radius, floorY } = measured
  const grid = gridSpacing(radius)
  const limits = cameraLimits(radius, 40)

  return (
    <Canvas
      className={props.stale ? 'stale' : undefined}
      camera={{ position: [400, 300, 400], fov: 40, near: 1, far: 10000 }}
      dpr={[1, 2]}
      data-testid="viewer-canvas"
    >
      <color attach="background" args={['#12151a']} />
      {/* Ground colour is a real fill, not the near-black it was: it is the only
          thing a hemisphere light gives a downward-facing face, and the underside
          of a mold half is exactly what someone flips the view round to inspect. */}
      <ambientLight intensity={0.28} />
      <hemisphereLight intensity={0.55} color="#d6e3f5" groundColor="#5d6675" />
      <directionalLight position={[300, 500, 400]} intensity={1.15} />
      <directionalLight position={[-400, 250, -300]} intensity={0.45} />
      <CameraLight intensity={0.55} />
      {/* Sized to the model and finite. An infinite grid keeps drawing cells out
          to the fade distance, and at a shallow angle those far cells alias into
          a shimmer that reads as the whole floor shaking whenever the camera
          moves - which, with damping, continues after the drag ends. Ending the
          grid a few model-radii out removes the aliasing rather than hiding it. */}
      <Grid
        args={[grid.extent, grid.extent]}
        cellSize={grid.cell}
        cellColor="#2a3038"
        sectionSize={grid.section}
        sectionColor="#3a434f"
        position={[0, floorY - radius * 0.04, 0]}
        fadeDistance={grid.extent}
        fadeStrength={1.5}
        // A floor, so it is only a floor from above. Left double-sided it draws
        // across the model the moment you tip the camera under the parting plane
        // - which is exactly when you are trying to look at the cavity.
        side={THREE.FrontSide}
      />
      <Suspense fallback={null}>
        {props.url && (
          <MoldScene key={`${props.url}-${key}`} {...props} url={props.url} onMeasured={setMeasured} />
        )}
      </Suspense>
      {/* Damping at 0.12 coasts for several seconds after a drag; the camera is
          still moving that whole time. 0.25 keeps the motion smooth but settles
          quickly, so the scene is actually still when it looks still. */}
      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.25}
        minDistance={limits.minDistance}
        maxDistance={limits.maxDistance}
      />
    </Canvas>
  )
}
