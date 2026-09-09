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
 * parting plane, +Z the plug direction). The scene is rotated -90 degrees about
 * X so that CAD +Z becomes screen up, and the camera is fitted to the model's
 * real bounding box, so a 235 mm plate frames the same way as a 500 mm one.
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

function MoldScene({ url, partMode, viewMode, showMale, showFemale }: Omit<ViewerProps, 'stale' | 'resetToken'> & { url: string }) {
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
    camera.position.set(centre.x + distance * 0.7, centre.z + distance * 0.5, centre.y + distance * 0.7)
    camera.near = distance / 100
    camera.far = distance * 20
    camera.updateProjectionMatrix()
    if (controls) {
      controls.target.set(centre.x, centre.z, -centre.y)
      controls.update()
    }
  }, [cloned, camera, controls])

  return <primitive object={cloned} rotation={[-Math.PI / 2, 0, 0]} />
}

export function Viewer(props: ViewerProps) {
  const [key, setKey] = useState(0)
  useEffect(() => setKey((k) => k + 1), [props.resetToken])

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
      <Grid
        args={[1200, 1200]}
        cellSize={10}
        cellColor="#2a3038"
        sectionSize={50}
        sectionColor="#3a434f"
        position={[0, -20, 0]}
        infiniteGrid
        fadeDistance={1800}
      />
      <Suspense fallback={null}>
        {props.url && <MoldScene key={`${props.url}-${key}`} {...props} url={props.url} />}
      </Suspense>
      <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
    </Canvas>
  )
}
