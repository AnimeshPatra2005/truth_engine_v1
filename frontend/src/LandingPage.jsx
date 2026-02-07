import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import './LandingPage.css';

function LandingPage() {
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const canvasRef = useRef(null);
    const rotationRef = useRef(90); // Start with vertical split (90 degrees)

    // ============================================
    // PARTICLE CANVAS ANIMATION WITH COLOR INVERSION
    // ============================================

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;

        const particles = [];
        const particleCount = 100; // Increased to 250 for denser coverage
        let mouse = { x: null, y: null, radius: 150 };


        // Get the current rotation angle for the split line
        const getRotation = () => rotationRef.current;

        // Calculate signed distance from the split line (negative = white side, positive = black side)
        const getSignedDistance = (x, y, rotation) => {
            const cx = canvas.width / 2;
            const cy = canvas.height / 2;
            // CORRECTED: CSS 0deg is Up, Math 0deg is Right.
            // CSS 90deg is Right.
            // We need to offset by -90 degrees to match CSS gradient direction.
            const theta = ((rotation - 90) * Math.PI) / 180;
            return (x - cx) * Math.cos(theta) + (y - cy) * Math.sin(theta);
        };

        // Get particle color with sharp transition at boundary
        const getParticleColor = (x, y, rotation, alpha = 0.8) => {
            const d = getSignedDistance(x, y, rotation);
            const transitionZone = 40; // Increased zone for visible smooth transition

            // Clamp the blend factor between 0 and 1
            // d < -transitionZone => fully on white side => black particle
            // d > transitionZone => fully on black side => white particle
            let blend = (d + transitionZone) / (2 * transitionZone);

            blend = Math.max(0, Math.min(1, blend));

            // Interpolate from black (0,0,0) to white (255,255,255)
            const colorValue = Math.round(blend * 255);
            return `rgba(${colorValue}, ${colorValue}, ${colorValue}, ${alpha})`;
        };

        class Particle {
            constructor() {
                this.x = Math.random() * canvas.width;
                this.y = Math.random() * canvas.height;
                this.size = Math.random() * 5 + 1; // Varied size 1-6px
                this.baseX = this.x;
                this.baseY = this.y;
                this.density = Math.random() * 30 + 1;
                this.vx = Math.random() * 0.5 - 0.25;
                this.vy = Math.random() * 0.5 - 0.25;
            }

            draw() {
                const rotation = getRotation();
                ctx.fillStyle = getParticleColor(this.x, this.y, rotation, 0.9);
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
                ctx.closePath();
                ctx.fill();
            }

            update() {
                this.baseX += this.vx;
                this.baseY += this.vy;

                if (this.baseX < 0 || this.baseX > canvas.width) this.vx *= -1;
                if (this.baseY < 0 || this.baseY > canvas.height) this.vy *= -1;

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
                    this.x -= directionX;
                    this.y -= directionY;
                } else {
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

        for (let i = 0; i < particleCount; i++) {
            particles.push(new Particle());
        }

        // connect() removed for cleaner look

        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            for (let i = 0; i < particles.length; i++) {
                particles[i].update();
                particles[i].draw();
            }
            requestAnimationFrame(animate);
        }

        animate();

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

        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseout', handleMouseOut);
            window.removeEventListener('resize', handleResize);
        };
    }, []);

    // ============================================
    // GSAP SCROLL ANIMATIONS - Rotating Split ONLY
    // ============================================

    useEffect(() => {
        if (window.innerWidth < 768) return;

        const loadGSAP = async () => {
            const { gsap } = await import('gsap');
            const { ScrollTrigger } = await import('gsap/ScrollTrigger');

            gsap.registerPlugin(ScrollTrigger);

            // Animate the rotation of the split background
            // This is the ONLY animation - no transform/opacity on content sections
            // as that would create stacking contexts breaking mix-blend-mode
            // Monotonic Rotation Logic - Continuous
            // The goal is constant rotation during scroll, aligning horizontal states (0, 180, 360) with sections.
            // Alignment Plan:
            // - Start (Hero): 90deg (Vertical)
            // - Scroll to Features (~30%): 180deg (Horizontal)
            // - Scroll to How it Works (~60%): 360deg (Horizontal)
            // - Scroll to End (~90%): 540deg (Horizontal)

            const proxy = { rotation: 90 };

            const updateRotation = () => {
                rotationRef.current = proxy.rotation;
                document.documentElement.style.setProperty('--split-rotation', `${proxy.rotation}deg`);
            };

            const tl = gsap.timeline({
                scrollTrigger: {
                    trigger: '.landing-page',
                    start: 'top top',
                    end: 'bottom bottom',
                    scrub: 0.5,
                }
            });

            // Use 'none' ease for truly continuous rotation
            tl.to(proxy, { rotation: 180, duration: 1, ease: 'none', onUpdate: updateRotation })
                .to(proxy, { rotation: 360, duration: 1, ease: 'none', onUpdate: updateRotation })
                .to(proxy, { rotation: 540, duration: 1, ease: 'none', onUpdate: updateRotation });


        };

        loadGSAP();

        return () => {
            if (window.ScrollTrigger) {
                window.ScrollTrigger.getAll().forEach(trigger => trigger.kill());
            }
        };
    }, []);

    return (

        <div className="landing-page">
            {/* Split Background */}
            <div className="split-background"></div>

            {/* Particle Canvas */}
            <canvas ref={canvasRef} className="particle-canvas"></canvas>

            {/* ============================================ */}
            {/* NAVIGATION BAR - Integrated into page */}
            {/* ============================================ */}
            <nav className="navbar">
                <div className="container">
                    <div className="nav-content">
                        {/* Unified nav links container for even spacing */}
                        <div className="nav-links">
                            <a href="#features">FEATURES</a>
                            <a href="#how-it-works">HOW IT WORKS</a>
                            <a href="#about">ABOUT</a>
                            <Link to="/try" className="nav-link-try">TRY NOW</Link>
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

                {/* Mobile Menu */}
                <div className={`mobile-menu ${isMenuOpen ? 'active' : ''}`}>
                    <a href="#features" onClick={() => setIsMenuOpen(false)}>FEATURES</a>
                    <a href="#how-it-works" onClick={() => setIsMenuOpen(false)}>HOW IT WORKS</a>
                    <a href="#about" onClick={() => setIsMenuOpen(false)}>ABOUT</a>
                    <Link to="/try" onClick={() => setIsMenuOpen(false)}>TRY NOW</Link>
                </div>
            </nav>

            {/* ============================================ */}
            {/* HERO SECTION - SATYA Typography */}
            {/* ============================================ */}
            <section className="hero">
                <div className="hero-content">
                    <h1 className="hero-title">SATYA</h1>
                    <p className="hero-quote">"Truth starts with facts and ends with implications"</p>
                    <div className="hero-actions">
                        <Link to="/try" className="btn-primary btn-large">
                            <span>Try Now</span>
                            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                                <path d="M7.5 15L12.5 10L7.5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                        </Link>
                    </div>
                </div>
            </section>

            {/* ============================================ */}
            {/* FEATURES SECTION */}
            {/* ============================================ */}
            <section id="features" className="features">
                <div className="container">
                    <div className="section-header">
                        <h2 className="section-title">Powerful Features</h2>
                        <p className="section-description">Everything you need to verify video content with confidence</p>
                    </div>
                    <div className="features-grid">
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

                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </div>
                            <h3 className="feature-title">AI Fact Verification</h3>
                            <p className="feature-description">Cross-reference claims against trusted sources for accurate verification</p>
                        </div>

                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM11 19.93C7.05 19.44 4 16.08 4 12C4 11.38 4.08 10.79 4.21 10.21L9 15L11 17V19.93ZM17.9 17.39C17.64 16.8 16.9 16.42 16.29 16.13L15 15.5V11.3C15 11.13 14.87 11 14.7 11H11.3C11.13 11 11 10.87 11 10.7V7.5C11 7.22 11.22 7 11.5 7H14.5C14.78 7 15 6.78 15 6.5V4.3C18.18 5.66 20.34 8.76 20.34 12.3C20.34 14.04 19.74 15.65 18.74 16.95L17.9 17.39Z" fill="currentColor" />
                                </svg>
                            </div>
                            <h3 className="feature-title">Real-Time Knowledge</h3>
                            <p className="feature-description">Leverages live internet access to verify claims against the very latest information</p>
                        </div>

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

                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <path d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <circle cx="8" cy="10" r="1.5" fill="currentColor" />
                                    <circle cx="12" cy="10" r="1.5" fill="currentColor" />
                                    <circle cx="16" cy="10" r="1.5" fill="currentColor" />
                                </svg>
                            </div>
                            <h3 className="feature-title">Expert Chatbot</h3>
                            <p className="feature-description">Chat with an AI expert that has complete knowledge of the entire analysis</p>
                        </div>

                        <div className="feature-card">
                            <div className="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                    <path d="M23 19C23 19.5304 22.7893 20.0391 22.4142 20.4142C22.0391 20.7893 21.5304 21 21 21H3C2.46957 21 1.96086 20.7893 1.58579 20.4142C1.21071 20.0391 1 19.5304 1 19V8C1 7.46957 1.21071 6.96086 1.58579 6.58579C1.96086 6.21071 2.46957 6 3 6H7L9 3H15L17 6H21C21.5304 6 22.0391 6.21071 22.4142 6.58579C22.7893 6.96086 23 7.46957 23 8V19Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <circle cx="12" cy="13" r="4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </div>
                            <h3 className="feature-title">Image Analysis</h3>
                            <p className="feature-description">Advanced vision AI analyzes visual context and images within the video</p>
                        </div>
                    </div>
                </div>
            </section>

            {/* ============================================ */}
            {/* HOW IT WORKS SECTION */}
            {/* ============================================ */}
            <section id="how-it-works" className="how-it-works">
                <div className="container">
                    <div className="section-header">
                        <h2 className="section-title">How It Works</h2>
                        <p className="section-description">Three simple steps to verify any video content</p>
                    </div>
                    <div className="steps-container">
                        <div className="step-card">
                            <div className="step-number">01</div>
                            <div className="step-content">
                                <h3 className="step-title">Upload Video or Query</h3>
                                <p className="step-description">Drag and drop a video, paste a URL, or simply type a text query to get started.</p>
                            </div>
                            <div className="step-visual">
                                <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                                    <rect x="8" y="16" width="48" height="40" rx="4" stroke="currentColor" strokeWidth="2" />
                                    <path d="M32 28V40M32 28L28 32M32 28L36 32" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </div>
                        </div>

                        <div className="step-arrow">
                            <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
                                <path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                        </div>

                        <div className="step-card">
                            <div className="step-number">02</div>
                            <div className="step-content">
                                <h3 className="step-title">AI Processing</h3>
                                <p className="step-description">Our AI extracts transcripts, analyzes images, and verifies every claim found.</p>
                            </div>
                            <div className="step-visual">
                                <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                                    <circle cx="32" cy="32" r="20" stroke="currentColor" strokeWidth="2" />
                                    <path d="M32 20V32L40 36" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                                </svg>
                            </div>
                        </div>

                        <div className="step-arrow">
                            <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
                                <path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                        </div>

                        <div className="step-card">
                            <div className="step-number">03</div>
                            <div className="step-content">
                                <h3 className="step-title">Get Results & Chat</h3>
                                <p className="step-description">Receive detailed results and discuss them with our expert chatbot.</p>
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
            {/* ABOUT SECTION */}
            {/* ============================================ */}
            <section id="about" className="about-section">
                <div className="container">
                    <div className="about-content">
                        <h2 className="section-title">Why SATYA?</h2>
                        <p className="about-text">
                            In an era of misinformation, SATYA empowers you to verify video content with confidence.
                            Our advanced AI technology combines speech recognition, natural language processing, and
                            fact-checking algorithms to deliver accurate, transparent results you can trust.
                        </p>
                    </div>
                </div>
            </section>

            {/* ============================================ */}
            {/* CTA SECTION */}
            {/* ============================================ */}
            <section className="cta-section">
                <div className="container">
                    <div className="cta-content">
                        <h2 className="cta-title">Ready to Verify the Truth?</h2>
                        <p className="cta-description">Start fact-checking videos with AI-powered precision today</p>
                        <Link to="/try" className="btn-primary btn-large">
                            <span>Try SATYA Now</span>
                            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                                <path d="M7.5 15L12.5 10L7.5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                        </Link>
                    </div>
                </div>
            </section>

            {/* ============================================ */}
            {/* FOOTER */}
            {/* ============================================ */}
            <footer className="footer">
                <div className="container">
                    <div className="footer-grid">
                        <div className="footer-box">
                            <div className="logo">
                                <span>SATYA</span>
                            </div>
                            <p className="footer-tagline">AI-Powered Video Fact Checking</p>
                        </div>

                        <div className="footer-box">
                            <h4>Quick Links</h4>
                            <div className="footer-links-list">
                                <a href="#features">Features</a>
                                <a href="#how-it-works">How It Works</a>
                                <a href="#about">About</a>
                                <Link to="/try">Try It Now</Link>
                            </div>
                        </div>
                    </div>
                </div>
            </footer>
        </div>
    );
}

export default LandingPage;
