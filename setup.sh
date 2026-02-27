#!/bin/bash
# Magnolia Analytics — First-time setup script
# Run this ONCE to get everything installed and ready.

echo ""
echo "🌿 Magnolia Analytics — Setup"
echo "================================"
echo ""

# Install Python packages
echo "Step 1/3: Installing Python packages..."
pip install -r requirements.txt
echo "  ✓ Packages installed"
echo ""

# Set up the database
echo "Step 2/3: Setting up the database..."
flask db init 2>/dev/null || true
flask db migrate -m "initial schema" 2>/dev/null
flask db upgrade
echo "  ✓ Database ready"
echo ""

# Seed default courses
echo "Step 3/3: Adding default courses (Seaford GC etc.)..."
python seed.py
echo ""

echo "================================"
echo "✅ Setup complete!"
echo ""
echo "To start the app, run:  sh start.sh"
echo "Then open:  http://127.0.0.1:5000"
echo ""
