import FooterFlourish from "../ui/FooterFlourish";

interface FooterProps {
  variant?: "home" | "dashboard" | "builder" | "trace";
}

export default function Footer({ variant = "home" }: FooterProps) {
  const footerClass = variant === "home" 
    ? "home-footer" 
    : variant === "dashboard" 
    ? "dashboard-footer" 
    : variant === "trace"
    ? "trace-footer"
    : "builder-footer";

  return (
    <footer className={footerClass} style={{ display: "flex", justifyContent: "center", alignItems: "center" }}>
      <FooterFlourish />
    </footer>
  );
}

