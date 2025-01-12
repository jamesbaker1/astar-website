import React from 'react';
import { motion } from 'framer-motion';

// Simple inline styling for demonstration.
// You can switch to a CSS file, styled-components, etc. if preferred.
const styles = {
  container: {
    fontFamily: "'Helvetica Neue', Arial, sans-serif",
    margin: 0,
    padding: 0,
    color: '#333',
    lineHeight: 1.6,
  },
  header: {
    backgroundColor: '#0a192f',
    color: '#fff',
    padding: '2rem',
    textAlign: 'center',
    marginBottom: '1rem',
  },
  title: {
    margin: 0,
    fontSize: '2.5rem',
  },
  subTitle: {
    margin: '1rem 0 0 0',
    fontSize: '1.2rem',
    fontWeight: 'normal',
    opacity: 0.8,
  },
  content: {
    padding: '2rem 1rem',
    maxWidth: '960px',
    margin: '0 auto',
  },
  featuresGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr',
    gap: '1rem',
    margin: '2rem 0',
  },
  featureItem: {
    backgroundColor: '#f7f7f7',
    borderRadius: '8px',
    padding: '1rem',
  },
  featureTitle: {
    fontSize: '1.2rem',
    margin: '0 0 0.5rem 0',
  },
  highlight: {
    color: '#007acc',
    fontWeight: 'bold',
  },
  callout: {
    backgroundColor: '#cceeff',
    borderRadius: '8px',
    padding: '1rem',
    marginTop: '1rem',
  },
  footer: {
    textAlign: 'center',
    padding: '1rem',
    backgroundColor: '#f0f0f0',
    marginTop: '2rem',
  },
};

// Framer Motion variants for container and items
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      // Stagger the child elements by 0.2 seconds
      staggerChildren: 0.2,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.6,
    },
  },
};

function App() {
  return (
    <div style={styles.container}>
      {/* Animated Header / Hero Section */}
      <motion.header
        style={styles.header}
        initial={{ opacity: 0, y: -50 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7 }}
      >
        <h1 style={styles.title}>World’s First Drone Piloting Foundational Model</h1>
        <p style={styles.subTitle}>
          Empowering drones with onboard intelligence, real-time obstacle avoidance, and open-ended capabilities.
        </p>
      </motion.header>

      {/* Main content with staggered animations */}
      <main style={styles.content}>
        <motion.section
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          <h2>Key Features</h2>

          <motion.div style={styles.featuresGrid} variants={containerVariants}>
            {/* Feature 1 */}
            <motion.div style={styles.featureItem} variants={itemVariants}>
              <h3 style={styles.featureTitle}>Runs Onboard with 8B Parameters</h3>
              <p>
                Our foundational model boasts{' '}
                <span style={styles.highlight}>8 billion parameters</span>,
                carefully optimized to run directly on drones—no offloading required.
              </p>
            </motion.div>
            {/* Feature 2 */}
            <motion.div style={styles.featureItem} variants={itemVariants}>
              <h3 style={styles.featureTitle}>Sub 20ms Obstacle Avoidance</h3>
              <p>
                Integrated flight path planning enables{' '}
                <span style={styles.highlight}>under 20ms response</span> times
                to avoid unexpected obstacles, even in complex environments.
              </p>
            </motion.div>
            {/* Feature 3 */}
            <motion.div style={styles.featureItem} variants={itemVariants}>
              <h3 style={styles.featureTitle}>Open-Ended Task Versatility</h3>
              <p>
                From package delivery to aerial photography, the model adapts to a{' '}
                <span style={styles.highlight}>variety of tasks</span> thanks to
                its advanced training.
              </p>
            </motion.div>
            {/* Feature 4 */}
            <motion.div style={styles.featureItem} variants={itemVariants}>
              <h3 style={styles.featureTitle}>Trained on Millions of Hours of Flight</h3>
              <p>
                Our dataset includes{' '}
                <span style={styles.highlight}>millions of flight-hours</span>{' '}
                across various terrains, weather conditions, and mission requirements.
              </p>
            </motion.div>
            {/* Feature 5 */}
            <motion.div style={styles.featureItem} variants={itemVariants}>
              <h3 style={styles.featureTitle}>Ask Your Drone How It Thinks</h3>
              <p>
                Beyond real-time piloting, query the drone to understand{' '}
                <span style={styles.highlight}>its decisions and observations</span>{' '}
                directly from its onboard AI.
              </p>
            </motion.div>
          </motion.div>
        </motion.section>

        {/* Coming soon (fade-in from below) */}
        <motion.section
          style={styles.callout}
          variants={itemVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.5 }}
        >
          <h2 style={{ marginTop: 0 }}>Coming Soon:</h2>
          <p>
            A <span style={styles.highlight}>0.5B parameter model</span> designed for
            ultra-low-power <strong>super edge devices</strong>—bringing the next level
            of intelligence to smaller, more affordable drones.
          </p>
        </motion.section>
      </main>

      {/* Footer */}
      <footer style={styles.footer}>
        <p>© 2025 DroneAI Inc. All rights reserved.</p>
      </footer>
    </div>
  );
}

export default App;
