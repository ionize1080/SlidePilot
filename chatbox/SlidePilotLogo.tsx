import type { SVGProps } from 'react'

export default function SlidePilotLogo(props: SVGProps<SVGSVGElement>) {
  return <svg width="36" height="36" viewBox="0 0 36 36" fill="none" aria-hidden="true" {...props}>
    <rect x="1" y="1" width="34" height="34" rx="10" fill="#182836" />
    <path d="M10 9.5h15a1.5 1.5 0 0 1 1.5 1.5v10a1.5 1.5 0 0 1-1.5 1.5H10A1.5 1.5 0 0 1 8.5 21V11A1.5 1.5 0 0 1 10 9.5Z" stroke="#6FE0C5" strokeWidth="1.5" />
    <path d="M17.5 23v4m-4 0h8m-8-13h7m-7 4h4" stroke="#6FE0C5" strokeWidth="1.5" strokeLinecap="round" />
    <path d="m21 17 9-3-3 9-2-4-4-2Z" fill="#E8F5F0" stroke="#182836" strokeWidth="1.3" strokeLinejoin="round" />
  </svg>
}
