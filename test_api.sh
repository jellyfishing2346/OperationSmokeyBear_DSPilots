#!/bin/bash
# Test Script for Operation Smokey Bear API

echo "🧪 Testing Operation Smokey Bear API"
echo "====================================="
echo ""

# Test data
TRANSCRIPT="Engine 201 responded to a reported kitchen fire at 1287 Maple Ave. Light smoke was showing from a two-story private home on arrival. Crew advanced a 1¾ inch hose line into the first-floor kitchen where flames were found on the stovetop and nearby cabinets. Fire was extinguished with water, and cabinets were overhauled to ensure no hidden fire. Ventilation performed by Truck 107. Cause determined to be unattended cooking oil. Smoke alarm activated and warned residents. One adult resident evaluated for smoke inhalation but refused transport. No firefighter injuries."

# Detect API URL
if [ -z "$1" ]; then
    API_URL="http://localhost/categorize-transcript"
    echo "Using local API: $API_URL"
else
    API_URL="$1/categorize-transcript"
    echo "Using custom API: $API_URL"
fi

echo ""
echo "📝 Test transcript:"
echo "$TRANSCRIPT"
echo ""
echo "🚀 Sending request to API..."
echo ""

# Make request
RESPONSE=$(curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -d "{\"transcript\": \"$TRANSCRIPT\"}" \
    --max-time 120)

# Check if request was successful
if [ $? -eq 0 ]; then
    echo "✅ API Response received!"
    echo ""
    
    # Pretty print JSON (if jq is available)
    if command -v jq &> /dev/null; then
        echo "$RESPONSE" | jq '.'
        
        # Show key extracted fields
        echo ""
        echo "🔍 Key Extracted Fields:"
        echo "========================"
        echo "Incident Type: $(echo "$RESPONSE" | jq -r '.fields.incident_final_type.value')"
        echo "Location: $(echo "$RESPONSE" | jq -r '.fields.incident_location.value')"
        echo "Fire Involved: $(echo "$RESPONSE" | jq -r '.fields.fire.value')"
        echo "Actions Taken: $(echo "$RESPONSE" | jq -r '.fields.incident_actions_taken.value')"
        echo "Cause: $(echo "$RESPONSE" | jq -r '.fields.structure_fire_cause.value')"
        echo ""
    else
        echo "$RESPONSE"
        echo ""
        echo "💡 Tip: Install 'jq' for prettier JSON output: apt install jq"
    fi
    
    echo "✅ Test completed successfully!"
else
    echo "❌ API request failed!"
    echo "Possible issues:"
    echo "  - Services not running (check: docker-compose ps)"
    echo "  - Ollama model not downloaded (check: docker exec ollama ollama list)"
    echo "  - Port conflicts"
    echo ""
    echo "Debug commands:"
    echo "  docker-compose logs backend"
    echo "  docker-compose logs ollama"
    exit 1
fi

