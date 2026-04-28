#!/bin/bash
# GST Rate Scraping Tool — Runner Script
# Usage: ./run.sh [command] [options]
#
# Commands:
#   full-run       Run complete pipeline (default)
#   fresh          Clean previous output and run fresh
#   scrape         Fetch and parse sources only
#   build          Normalize, classify, and expand
#   export         Export to Excel/CSV
#   status         Show pipeline status
#   test           Run test suite
#   clean          Remove output files and reset

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG="config/config.yaml"
TARGET_ROWS=100000
VENV_DIR=".venv"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_banner() {
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║     GST Rate Scraping & Excel Generation Tool       ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Setup virtual environment if not exists
setup_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${YELLOW}Creating virtual environment...${NC}"
        python3 -m venv "$VENV_DIR"
        source "$VENV_DIR/bin/activate"
        echo -e "${YELLOW}Installing dependencies...${NC}"
        pip install -r requirements.txt
        echo -e "${GREEN}✅ Setup complete.${NC}"
    else
        source "$VENV_DIR/bin/activate"
    fi
}

COMMAND="${1:-full-run}"
shift 2>/dev/null || true

case "$COMMAND" in
    full-run)
        print_banner
        setup_venv
        echo -e "${GREEN}▶ Running full pipeline...${NC}"
        python main.py full-run --config "$CONFIG" --target-rows "$TARGET_ROWS" "$@"
        ;;
    fresh)
        print_banner
        echo -e "${YELLOW}Cleaning previous output...${NC}"
        rm -rf output/
        setup_venv
        echo -e "${GREEN}▶ Running fresh pipeline...${NC}"
        python main.py full-run --config "$CONFIG" --target-rows "$TARGET_ROWS" "$@"
        ;;
    scrape)
        print_banner
        setup_venv
        echo -e "${GREEN}▶ Scraping sources...${NC}"
        python main.py scrape --config "$CONFIG" "$@"
        ;;
    build)
        print_banner
        setup_venv
        echo -e "${GREEN}▶ Building product dataset...${NC}"
        python main.py build-products --config "$CONFIG" --target-rows "$TARGET_ROWS" "$@"
        ;;
    export)
        print_banner
        setup_venv
        echo -e "${GREEN}▶ Exporting data...${NC}"
        python main.py export --config "$CONFIG" "$@"
        ;;
    status)
        setup_venv
        python main.py status --config "$CONFIG"
        ;;
    test)
        setup_venv
        echo -e "${GREEN}▶ Running tests...${NC}"
        python -m pytest tests/ -v --cov=gst_scraper "$@"
        ;;
    clean)
        echo -e "${YELLOW}Cleaning output files...${NC}"
        rm -rf output/
        echo -e "${GREEN}✅ Output directory removed.${NC}"
        ;;
    *)
        echo -e "${RED}Unknown command: $COMMAND${NC}"
        echo ""
        echo "Usage: ./run.sh [command]"
        echo ""
        echo "Commands:"
        echo "  full-run   Run complete pipeline (default, resumes from last state)"
        echo "  fresh      Clean previous output and run fresh pipeline"
        echo "  scrape     Fetch and parse sources only"
        echo "  build      Normalize, classify, and expand"
        echo "  export     Export to Excel/CSV"
        echo "  status     Show pipeline status"
        echo "  test       Run test suite"
        echo "  clean      Remove output files and reset"
        exit 1
        ;;
esac
