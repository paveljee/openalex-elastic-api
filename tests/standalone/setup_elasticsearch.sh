#!/bin/bash
set -e

# Elasticsearch Setup Script for Author Matching Tests
# Downloads, configures, and starts Elasticsearch 8.9.0

ES_VERSION="8.9.0"
ES_DIR="elasticsearch-${ES_VERSION}"
ES_TARBALL="${ES_DIR}-linux-x86_64.tar.gz"
ES_URL="https://artifacts.elastic.co/downloads/elasticsearch/${ES_TARBALL}"

echo "=== Elasticsearch Setup for Author Matching Tests ==="
echo ""

# Check if already downloaded
if [ -d "$ES_DIR" ]; then
    echo "✓ Elasticsearch already downloaded at $ES_DIR"
else
    echo "→ Downloading Elasticsearch ${ES_VERSION}..."
    wget -q --show-progress "$ES_URL"

    echo "→ Extracting..."
    tar -xzf "$ES_TARBALL"
    rm "$ES_TARBALL"
    echo "✓ Elasticsearch extracted to $ES_DIR"
fi

# Configure Elasticsearch
echo ""
echo "→ Configuring Elasticsearch..."
cat > "$ES_DIR/config/elasticsearch.yml" << 'EOF'
# Single-node cluster for testing
cluster.name: openalex-test
node.name: node-1
network.host: 127.0.0.1
http.port: 9200
discovery.type: single-node

# Disable security for local testing
xpack.security.enabled: false
xpack.security.enrollment.enabled: false
xpack.security.http.ssl.enabled: false
xpack.security.transport.ssl.enabled: false
EOF
echo "✓ Configuration written"

# Create elasticsearch user if running as root
if [ "$EUID" -eq 0 ]; then
    echo ""
    echo "→ Creating elasticsearch user (cannot run as root)..."
    if ! id -u elasticsearch > /dev/null 2>&1; then
        useradd -r -s /bin/false elasticsearch
    fi
    chown -R elasticsearch:elasticsearch "$ES_DIR"
    echo "✓ Ownership set to elasticsearch user"

    RUN_CMD="sudo -u elasticsearch"
else
    RUN_CMD=""
fi

# Start Elasticsearch
echo ""
echo "→ Starting Elasticsearch..."
echo "  (Logs will be in $ES_DIR/logs/)"
$RUN_CMD "$ES_DIR/bin/elasticsearch" -d -p elasticsearch.pid

# Wait for Elasticsearch to be ready
echo ""
echo "→ Waiting for Elasticsearch to start..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:9200/_cluster/health > /dev/null 2>&1; then
        echo "✓ Elasticsearch is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "✗ Elasticsearch failed to start within 30 seconds"
        echo "  Check logs at: $ES_DIR/logs/openalex-test.log"
        exit 1
    fi
    sleep 1
done

# Create authors index with proper mappings
echo ""
echo "→ Creating authors-v16 index with mappings..."
curl -s -X PUT "http://127.0.0.1:9200/authors-v16" -H 'Content-Type: application/json' -d'
{
  "mappings": {
    "properties": {
      "id": {
        "type": "keyword"
      },
      "display_name": {
        "type": "text",
        "fields": {
          "folded": {
            "type": "text",
            "analyzer": "folding"
          },
          "keyword": {
            "type": "keyword"
          }
        }
      },
      "display_name_alternatives": {
        "type": "text",
        "fields": {
          "folded": {
            "type": "text",
            "analyzer": "folding"
          }
        }
      },
      "cited_by_count": {
        "type": "long"
      },
      "works_count": {
        "type": "long"
      }
    }
  },
  "settings": {
    "analysis": {
      "analyzer": {
        "folding": {
          "tokenizer": "standard",
          "filter": ["lowercase", "asciifolding"]
        }
      }
    }
  }
}
' > /dev/null
echo "✓ Index created with mappings"

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Elasticsearch is running at: http://127.0.0.1:9200"
echo ""
echo "Next steps:"
echo "  1. Populate index: python populate_es.py"
echo "  2. Run tests: python -m pytest test_real_ranking_comparison.py -v"
echo ""
echo "To stop Elasticsearch:"
echo "  kill \$(cat elasticsearch.pid)"
echo ""
