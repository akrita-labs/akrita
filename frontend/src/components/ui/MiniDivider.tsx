import { ReactNode } from "react";

interface MiniDividerProps {
  children?: ReactNode;
  className?: string;
}

export default function MiniDivider({ children, className = "" }: MiniDividerProps) {
  return (
    <div className={`mini-divider ${className}`}>
      <span></span>
      {children && <b>{children}</b>}
      <span></span>
    </div>
  );
}
