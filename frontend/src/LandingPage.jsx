import { useState } from 'react';
import { Link } from 'react-router-dom';
import './LandingPage.css';

function LandingPage() {
    const [isMenuOpen, setIsMenuOpen] = useState(false);

    return (
        <div className="landing-page">
            <nav className="navbar">
                <div className="container">
                    <div className="nav-content">
                        <div className="logo">
                            <span>Truth Engine</span>
                        </div>

                        <div className={`nav-links ${isMenuOpen ? 'active' : ''}`}>
                            <a href="#features">Features</a>
                            <a href="#how-it-works">How It Works</a>
                            <a href="#about">About</a>
                            <Link to="/try" className="btn-primary">Try It Now</Link>
                        </div>

                        <button
                            className="menu-toggle"
                            onClick={() => setIsMenuOpen(!isMenuOpen)}
                        >
                            <span></span>
                            <span></span>
                            <span></span>
                        </button>
                    </div>
                </div>
            </nav>
        </div>
    );
}

export default LandingPage;
