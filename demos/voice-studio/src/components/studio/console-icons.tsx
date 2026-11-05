import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & {
  readonly size?: number;
};

function Svg({ size = 16, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export function BrandWaveIcon(props: IconProps) {
  return (
    <Svg size={15} {...props}>
      <path d="M12 3v18M7 8v8M17 6v12M3 11v2M21 10v4" />
    </Svg>
  );
}

export function ConsoleActivityIcon(props: IconProps) {
  return (
    <Svg size={14} {...props}>
      <path d="M3 12h4l2-5 3 10 2-5h7" />
    </Svg>
  );
}

export function SlidersIcon(props: IconProps) {
  return (
    <Svg size={15} {...props}>
      <line x1="4" y1="21" x2="4" y2="14" />
      <line x1="4" y1="10" x2="4" y2="3" />
      <line x1="12" y1="21" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12" y2="3" />
      <line x1="20" y1="21" x2="20" y2="16" />
      <line x1="20" y1="12" x2="20" y2="3" />
      <line x1="2" y1="14" x2="6" y2="14" />
      <line x1="10" y1="8" x2="14" y2="8" />
      <line x1="18" y1="16" x2="22" y2="16" />
    </Svg>
  );
}

export function MicOnIcon(props: IconProps) {
  return (
    <Svg size={18} {...props}>
      <rect x="9" y="2" width="6" height="11" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 17v4M8 21h8" />
    </Svg>
  );
}

export function MicOffIcon(props: IconProps) {
  return (
    <Svg size={18} {...props}>
      <line x1="2" y1="2" x2="22" y2="22" />
      <path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2M5 10v2a7 7 0 0 0 12 5" />
      <path d="M15 9.34V5a3 3 0 0 0-5.68-1.33M9 9v3a3 3 0 0 0 5.12 2.12" />
      <line x1="12" y1="19" x2="12" y2="22" />
      <line x1="8" y1="22" x2="16" y2="22" />
    </Svg>
  );
}

export function SpeakerOnIcon(props: IconProps) {
  return (
    <Svg size={18} {...props}>
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M19 5a10 10 0 0 1 0 14" />
    </Svg>
  );
}

export function SpeakerOffIcon(props: IconProps) {
  return (
    <Svg size={18} {...props}>
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <line x1="22" y1="9" x2="16" y2="15" />
      <line x1="16" y1="9" x2="22" y2="15" />
    </Svg>
  );
}

export function VideoOnIcon(props: IconProps) {
  return (
    <Svg size={18} {...props}>
      <rect x="2" y="6" width="14" height="12" rx="2" />
      <polygon points="22 8 16 12 22 16 22 8" />
    </Svg>
  );
}

export function VideoOffIcon(props: IconProps) {
  return (
    <Svg size={18} {...props}>
      <path d="M16 16v1a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2m5.66 0H14a2 2 0 0 1 2 2v3.34l1 1L22 8v8" />
      <line x1="2" y1="2" x2="22" y2="22" />
    </Svg>
  );
}

export function PlaySampleIcon(props: IconProps) {
  return (
    <Svg size={13} {...props}>
      <polygon points="6 4 20 12 6 20 6 4" />
    </Svg>
  );
}

export function StopSampleIcon(props: IconProps) {
  return (
    <Svg size={13} {...props}>
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
    </Svg>
  );
}

export function PhoneEndIcon(props: IconProps) {
  return (
    <Svg size={17} {...props}>
      <path d="M10.7 13.3a16 16 0 0 0 6 2.6l1.7-1.7a1 1 0 0 1 1-.2c1.1.4 2.3.6 3.6.6a1 1 0 0 1 1 1V20a1 1 0 0 1-1 1C10.8 21 3 13.2 3 3a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.3.2 2.5.6 3.6a1 1 0 0 1-.2 1L7.2 9.3" />
      <line x1="21" y1="3" x2="15" y2="9" />
      <line x1="15" y1="3" x2="21" y2="9" />
    </Svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <Svg size={15} {...props}>
      <path d="M18 6 6 18M6 6l12 12" />
    </Svg>
  );
}

export function ExpandIcon(props: IconProps) {
  return (
    <Svg size={14} {...props}>
      <polyline points="15 3 21 3 21 9" />
      <polyline points="9 21 3 21 3 15" />
      <line x1="21" y1="3" x2="14" y2="10" />
      <line x1="3" y1="21" x2="10" y2="14" />
    </Svg>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <Svg size={14} {...props}>
      <polyline points="9 18 15 12 9 6" />
    </Svg>
  );
}

export function UploadIcon(props: IconProps) {
  return (
    <Svg size={14} {...props}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </Svg>
  );
}

export function CameraIcon(props: IconProps) {
  return (
    <Svg size={14} {...props}>
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
      <circle cx="12" cy="13" r="4" />
    </Svg>
  );
}
