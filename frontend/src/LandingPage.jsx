import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import './LandingPage.css';

function LandingPage() {
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const canvasRef = useRef(null);

    // ============================================
    // PARTICLE CANVAS ANIMATION
    // ============================================

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;

        const particles = [];
        const particleCount = 100; // Number of particles to create
        let mouse = { x: null, y: null, radius: 150 }; // Mouse interaction area

        // Particle class - each particle is an independent object
        class Particle {
            constructor() {
                // Random starting position
                this.x = Math.random() * canvas.width;
                this.y = Math.random() * canvas.height;
                this.size = Math.random() * 3 + 1; // Random size between 1-4px
                this.baseX = this.x; // Remember original position
                this.baseY = this.y;
                this.density = Math.random() * 30 + 1; // How much it reacts to mouse
                this.vx = Math.random() * 0.5 - 0.25; // Random velocity X
                this.vy = Math.random() * 0.5 - 0.25; // Random velocity Y
            }

            // Draw the particle on canvas
            draw() {
                ctx.fillStyle = 'rgba(168, 199, 250, 0.6)'; // Light blue color
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
                ctx.closePath();
                ctx.fill();
            }

            // Update particle position each frame
            update() {
                // Gentle floating movement
                this.baseX += this.vx;
                this.baseY += this.vy;

                // Bounce off edges
                if (this.baseX < 0 || this.baseX > canvas.width) this.vx *= -1;
                if (this.baseY < 0 || this.baseY > canvas.height) this.vy *= -1;

                // Mouse interaction - particles move away from cursor
                let dx = mouse.x - this.baseX;
                let dy = mouse.y - this.baseY;
                let distance = Math.sqrt(dx * dx + dy * dy);
                let forceDirectionX = dx / distance;
                let forceDirectionY = dy / distance;
                let maxDistance = mouse.radius;
                let force = (maxDistance - distance) / maxDistance;
                let directionX = forceDirectionX * force * this.density;
                let directionY = forceDirectionY * force * this.density;

                if (distance < mouse.radius) {
                    // Push particle away from mouse
                    this.x -= directionX;
                    this.y -= directionY;
                } else {
                    // Return to base position
                    if (this.x !== this.baseX) {
                        let dx = this.x - this.baseX;
                        this.x -= dx / 10;
                    }
                    if (this.y !== this.baseY) {
                        let dy = this.y - this.baseY;
                        this.y -= dy / 10;
                    }
                }
            }
        }

        // Create all particles
        for (let i = 0; i < particleCount; i++) {
            particles.push(new Particle());
        }

        // Connect nearby particles with lines
        function connect() {
            for (let a = 0; a < particles.length; a++) {
                for (let b = a; b < particles.length; b++) {
                    let dx = particles[a].x - particles[b].x;
                    let dy = particles[a].y - particles[b].y;
                    let distance = Math.sqrt(dx * dx + dy * dy);

                    // Only connect if particles are close enough
                    if (distance < 100) {
                        ctx.strokeStyle = `rgba(168, 199, 250, ${1 - distance / 100})`;
                        ctx.lineWidth = 0.5;
                        ctx.beginPath();
                        ctx.moveTo(particles[a].x, particles[a].y);
                        ctx.lineTo(particles[b].x, particles[b].y);
                        ctx.stroke();
                    }
                }
            }
        }

        // Animation loop - runs 60 times per second
        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height); // Clear canvas

            for (let i = 0; i < particles.length; i++) {
                particles[i].update();
                particles[i].draw();
            }
            connect(); // Draw lines between particles
            requestAnimationFrame(animate); // Loop
        }

        animate(); // Start animation

        // Event listeners for mouse interaction
        const handleMouseMove = (e) => {
            mouse.x = e.x;
            mouse.y = e.y;
        };

        const handleMouseOut = () => {
            mouse.x = null;
            mouse.y = null;
        };

        const handleResize = () => {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        };

        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseout', handleMouseOut);
        window.addEventListener('resize', handleResize);

        // Cleanup when component unmounts
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseout', handleMouseOut);
            window.removeEventListener('resize', handleResize);
        };
    }, []); // Empty dependency array = run once on mount

    return (
        <div className="landing-page">
            {/* ============================================ */}
            {/* PARTICLE CANVAS - Interactive Background */}
            {/* ============================================ */}
            <canvas ref={canvasRef} className="particle-canvas"></canvas>

            {/* ============================================ */}
            {/* NAVIGATION BAR */}
            {/* ============================================ */}
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

            {/* ============================================ */}
            {/* HERO SECTION - Main Landing Area */}
            {/* ============================================ */}
            <section className="hero">
                {/* Animated gradient orbs in background */}
                <div className="hero-background">
                    <div className="gradient-orb orb-1"></div>
                    <div className="gradient-orb orb-2"></div>
                    <div className="gradient-orb orb-3"></div>
                </div>

                <div className="container">
                    <div className="hero-content">
                        {/* Badge - small indicator */}
                        <div className="hero-badge">
                            <span className="badge-dot"></span>
                            AI-Powered Verification
                        </div>

                        {/* Main headline */}
                        <h1 className="hero-title">
                            Verify Truth in
                            <br />
                            <span className="gradient-text">Video Content</span>
                        </h1>

                        {/* Description */}
                        <p className="hero-description">
                            Upload any video, extract transcripts instantly, and get AI-powered fact-checking results.
                            Truth Engine analyzes claims and provides verified information in seconds.
                        </p>

                        {/* Call-to-action buttons */}
                        <div className="hero-actions">
                            <Link to="/try" className="btn-primary btn-large">
                                <span>Start Fact-Checking</span>
                                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                                    <path d="M7.5 15L12.5 10L7.5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </Link>
                            <a href="#how-it-works" className="btn-secondary btn-large">
                                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                                    <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="2" />
                                    <path d="M10 6V10L12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                                </svg>
                                <span>See How It Works</span>
                            </a>
                        </div>
                    </div>
                </div>
            </section>

            {/* ============================================ */}
            {/* FEATURES SECTION - 6 Feature Cards */}
            {/* ============================================ */}
            <section id="features" className="features">
                <div className="container">
                    <div className="section-header">
                        <h2 className="section-title">Powerful Features</h2>
                        <p className="section-description">Everything you need to verify video content with confidence</p>
                    </div>
                    <div className="features-grid">
                        {/* Feature Card 1 */}
                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <path d="M9 12L11 14L15 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
                                </svg>
                            </div>
                            <h3 className="feature-title">Instant Transcript Extraction</h3>
                            <p className="feature-description">Advanced AI extracts accurate transcripts from any video format in seconds</p>
                        </div>

                        {/* Feature Card 2 */}
                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <path d="M12 2L4 9V15C4 23 10 29 16 30C22 29 28 23 28 15V9L12 2Z" stroke="currentColor" strokeWidth="2" />
                                    <path d="M9 12L11 14L15 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </div>
                            <h3 className="feature-title">AI Fact Verification</h3>
                            <p className="feature-description">Cross-reference claims against trusted sources for accurate verification</p>
                        </div>

                        {/* Feature Card 3 */}
                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </div>
                            <h3 className="feature-title">Real-Time Analysis</h3>
                            <p className="feature-description">Get instant results as your video is processed with live progress updates</p>
                        </div>

                        {/* Feature Card 4 */}
                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" strokeWidth="2" />
                                    <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                                </svg>
                            </div>
                            <h3 className="feature-title">Source Citations</h3>
                            <p className="feature-description">Every fact check includes detailed sources and references for transparency</p>
                        </div>

                        {/* Feature Card 5 */}
                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
                                    <path d="M12 1v6M12 17v6M4.22 4.22l4.24 4.24M15.54 15.54l4.24 4.24M1 12h6M17 12h6M4.22 19.78l4.24-4.24M15.54 8.46l4.24-4.24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                                </svg>
                            </div>
                            <h3 className="feature-title">History Tracking</h3>
                            <p className="feature-description">Access all your previous fact-checks with organized history and search</p>
                        </div>

                        {/* Feature Card 6 */}
                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
                                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" stroke="currentColor" strokeWidth="2" />
                                </svg>
                            </div>
                            <h3 className="feature-title">Customizable Settings</h3>
                            <p className="feature-description">Adjust verification sensitivity and source preferences to your needs</p>
                        </div>
                    </div>
                </div>
            </section>

            {/* ============================================ */}
            {/* HOW IT WORKS SECTION - 3 Step Process */}
            {/* ============================================ */}
            <section id="how-it-works" className="how-it-works">
                <div className="container">
                    <div className="section-header">
                        <h2 className="section-title">How It Works</h2>
                        <p className="section-description">Three simple steps to verify any video content</p>
                    </div>
                    <div className="steps-container">
                        {/* Step 1 */}
                        <div className="step-card">
                            <div className="step-number">01</div>
                            <div className="step-content">
                                <h3 className="step-title">Upload Video</h3>
                                <p className="step-description">Drag and drop your video file or paste a URL. We support all major formats.</p>
                            </div>
                            <div className="step-visual">
                                <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                                    <rect x="8" y="16" width="48" height="40" rx="4" stroke="currentColor" strokeWidth="2" />
                                    <path d="M32 28V40M32 28L28 32M32 28L36 32" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </div>
                        </div>

                        {/* Arrow */}
                        <div className="step-arrow">→</div>

                        {/* Step 2 */}
                        <div className="step-card">
                            <div className="step-number">02</div>
                            <div className="step-content">
                                <h3 className="step-title">AI Processing</h3>
                                <p className="step-description">Our AI extracts the transcript and analyzes every claim made in the video.</p>
                            </div>
                            <div className="step-visual">
                                <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                                    <circle cx="32" cy="32" r="20" stroke="currentColor" strokeWidth="2" />
                                    <path d="M32 20V32L40 36" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                                </svg>
                            </div>
                        </div>

                        {/* Arrow */}
                        <div className="step-arrow">→</div>

                        {/* Step 3 */}
                        <div className="step-card">
                            <div className="step-number">03</div>
                            <div className="step-content">
                                <h3 className="step-title">Get Results</h3>
                                <p className="step-description">Receive detailed fact-check results with sources and confidence scores.</p>
                            </div>
                            <div className="step-visual">
                                <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                                    <path d="M28 32L32 36L44 24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <circle cx="32" cy="32" r="20" stroke="currentColor" strokeWidth="2" />
                                </svg>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* ============================================ */}
            {/* ABOUT SECTION - Why Truth Engine */}
            {/* ============================================ */}
            <section id="about" className="about-section">
                <div className="container">
                    <div className="about-content">
                        <h2 className="section-title">Why Truth Engine?</h2>
                        <p className="about-text">
                            In an era of misinformation, Truth Engine empowers you to verify video content with confidence.
                            Our advanced AI technology combines speech recognition, natural language processing, and
                            fact-checking algorithms to deliver accurate, transparent results you can trust.
                        </p>
                    </div>
                </div>
            </section>

            {/* ============================================ */}
            {/* CTA SECTION - Final Call-to-Action */}
            {/* ============================================ */}
            <section className="cta-section">
                <div className="container">
                    <div className="cta-content">
                        <h2 className="cta-title">Ready to Verify the Truth?</h2>
                        <p className="cta-description">Start fact-checking videos with AI-powered precision today</p>
                        <Link to="/try" className="btn-primary btn-large">
                            <span>Try Truth Engine Now</span>
                            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                                <path d="M7.5 15L12.5 10L7.5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                        </Link>
                    </div>
                </div>
            </section>
        </div>
    );
}

export default LandingPage;
