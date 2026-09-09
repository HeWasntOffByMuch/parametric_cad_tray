import { Suspense, useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
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

function MoldScene({ url, partMode, viewMode, showMale, showFemale, setExtent }: Omit<ViewerProps, 'stale' | 'resetToken'> & { url: string; setExtent: (r: number) => void }) {
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

  useEffect(() => {
    const box = new THREE.Box3().setFromObject(cloned)
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3())
    const centre = box.getCenter(new THREE.Vector3())
    const radius = Math.max(size.x, size.y, size.z) * 0.85
    const fov = ((camera as THREE.PerspectiveCamera).fov * Math.PI) / 180
    const distance = radius / Math.sin(fov / 2)
    // Plain world coordinates: the box already reflects the GLB's own Y-up
    // rotation, so there is nothing left to convert here.
    camera.position.set(
      centre.x + distance * 0.62,
      centre.y + distance * 0.55,
      centre.z + distance * 0.62,
    )
    // Clip to what is actually in front of the camera. A near/far spread wider
    // than the scene needs spends depth-buffer precision on empty space, and the
    // grid - a large coplanar surface at a shallow angle - is the first thing to
    // shimmer when it runs out.
    camera.near = Math.max(distance * 0.01, (distance - radius) * 0.5)
    camera.far = (distance + radius) * 4
    camera.updateProjectionMatrix()
    if (controls) {
      controls.target.copy(centre)
      controls.update()
    }
    setExtent(radius)
  }, [cloned, camera, controls, setExtent])

  // No rotation here. CadQuery's glTF exporter already writes the Z-up to Y-up
  // conversion onto the assembly's root node (a -90 degree quaternion about X),
  // so rotating again turned the whole 180 degrees and stood the plate on its
  // edge. The mesh data stays Z-up, which is why the explode offset above is
  // still along the parts' local Z - that is the press axis.
  return <primitive object={cloned} />
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
  const [radius, setRadius] = useState(150)
  useEffect(() => setKey((k) => k + 1), [props.resetToken])
  const grid = gridSpacing(radius)

  return (
    <Canvas
      className={props.stale ? 'stale' : undefined}
      camera={{ position: [400, 300, 400], fov: 40, near: 1, far: 10000 }}
      dpr={[1, 2]}
      data-testid="viewer-canvas"
    >
      <color attach="background" args={['#12151a']} />
      <hemisphereLight intensity={0.75} groundColor="#20242c" />
      <directionalLight position={[300, 500, 400]} intensity={1.6} castShadow />
      <directionalLight position={[-400, 200, -300]} intensity={0.5} />
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
        position={[0, -radius * 0.12, 0]}
        fadeDistance={grid.extent}
        fadeStrength={1.5}
      />
      <Suspense fallback={null}>
        {props.url && (
          <MoldScene key={`${props.url}-${key}`} {...props} url={props.url} setExtent={setRadius} />
        )}
      </Suspense>
      {/* Damping at 0.12 coasts for several seconds after a drag; the camera is
          still moving that whole time. 0.25 keeps the motion smooth but settles
          quickly, so the scene is actually still when it looks still. */}
      <OrbitControls makeDefault enableDamping dampingFactor={0.25} />
    </Canvas>
  )
}
