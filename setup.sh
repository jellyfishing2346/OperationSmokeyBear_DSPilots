#!/bin/bash
# Quick Setup Script for Operation Smokey Bear

set -e

echo "🔥 Operation Smokey Bear - Quick Setup 🔥"
echo "========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Installing..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    echo "✅ Docker installed!"
else
    echo "✅ Docker is already installed"
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Installing..."
    apt install docker-compose -y
    echo "✅ Docker Compose installed!"
else
    echo "✅ Docker Compose is already installed"
fi

echo ""
echo "📝 Creating environment configuration..."

# Create .env file if it doesn't exist
if [ ! -f "Backend/.env" ]; then
    cp Backend/env.example Backend/.env
    echo "✅ Created Backend/.env (edit if needed)"
else
    echo "⚠️  Backend/.env already exists (skipping)"
fi

echo ""
echo "🚀 Starting services with Docker Compose..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to start..."
sleep 10

echo ""
echo "🤖 Checking if Ollama is running..."
if docker ps | grep -q ollama; then
    echo "✅ Ollama is running"
    
    echo ""
    echo "📦 Downloading Qwen2.5 model (this may take 5-10 minutes)..."
    echo "You can choose a model size based on your RAM:"
    echo "  - qwen2.5:3b  (2GB RAM needed - fastest)"
    echo "  - qwen2.5:7b  (4GB RAM needed - balanced)"
    echo "  - qwen2.5:14b (8GB RAM needed - most accurate)"
    echo ""
    
    read -p "Which model would you like? (3b/7b/14b) [default: 7b]: " MODEL_CHOICE
    MODEL_CHOICE=${MODEL_CHOICE:-7b}
    
    echo "Pulling qwen2.5:${MODEL_CHOICE}..."
    docker exec ollama ollama pull qwen2.5:${MODEL_CHOICE}
    
    echo ""
    echo "✅ Model downloaded successfully!"
else
    echo "❌ Ollama is not running. Check logs: docker logs ollama"
    exit 1
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "🎉 Your API is now running at:"
echo "   http://localhost/"
echo ""
echo "📚 Next steps:"
echo "   1. Test the API: bash test_api.sh"
echo "   2. View logs: docker-compose logs -f"
echo "   3. Read deployment guide: DEPLOYMENT_GUIDE.md"
echo ""
echo "🔒 For production deployment:"
echo "   - Set up a domain name"
echo "   - Enable HTTPS with Let's Encrypt"
echo "   - Add API key authentication"
echo "   - Configure firewall"
echo ""

