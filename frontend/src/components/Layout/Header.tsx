import { Link } from "react-router-dom";

interface HeaderProps {
  className?: string;
}

export default function Header({ className = "home-header" }: HeaderProps) {
  return (
    <header className={className}>
      <Link className="home-brand" to="/" aria-label="AKRITA home">
        <span className="home-brand-name">AKRITA</span>
        <span className="home-brand-sub">AKRITAI</span>
      </Link>

      <nav className="home-nav" aria-label="Primary">
        <Link to="/dashboard">Dashboard</Link>
        <span aria-hidden="true">·</span>
        <Link to="/trace">Trace Viewer</Link>
        <span aria-hidden="true">·</span>
        <Link to="/builder">Builder</Link>
        <span aria-hidden="true">·</span>
        <Link to="/about">About</Link>
        <span aria-hidden="true">·</span>
        <a 
          href="https://github.com/akrita-labs/akrita/blob/main/docs/ARCHITECTURE.md" 
          target="_blank" 
          rel="noopener noreferrer"
        >
          Documentation
        </a>
        <span aria-hidden="true">·</span>
        <a 
          href="https://github.com/akrita-labs/akrita" 
          target="_blank" 
          rel="noopener noreferrer"
        >
          Github
        </a>
      </nav>

      <Link className="home-enter" to="/dashboard">Enter Keeper</Link>
    </header>
  );
}
