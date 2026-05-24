interface PanelCornersProps {
  prefix?: "panel" | "trace" | "builder";
}

export default function PanelCorners({ prefix = "panel" }: PanelCornersProps) {
  return (
    <>
      <span className={`${prefix}-corner corner-tl`} aria-hidden="true">✾</span>
      <span className={`${prefix}-corner corner-tr`} aria-hidden="true">✾</span>
      <span className={`${prefix}-corner corner-bl`} aria-hidden="true">✾</span>
      <span className={`${prefix}-corner corner-br`} aria-hidden="true">✾</span>
    </>
  );
}
