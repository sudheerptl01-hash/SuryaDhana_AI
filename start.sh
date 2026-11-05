#!/bin/bash
# SuryaDhana AI — One-Command Full Stack Startup
# Usage: ./start.sh [build|stop|logs|status]

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$PROJECT_ROOT/infra"
ENV_FILE="$PROJECT_ROOT/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────────────────────────────────────

print_header() {
  echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BLUE}$1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
  echo -e "${GREEN}✓${NC} $1"
}

print_error() {
  echo -e "${RED}✗${NC} $1"
}

print_info() {
  echo -e "${BLUE}ℹ${NC} $1"
}

print_warning() {
  echo -e "${YELLOW}⚠${NC} $1"
}

# ─────────────────────────────────────────────────────────────────────────────

check_prerequisites() {
  print_header "Checking Prerequisites"

  # Check Docker
  if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker Desktop."
    exit 1
  fi
  print_success "Docker is installed"

  # Check Docker daemon
  if ! docker info > /dev/null 2>&1; then
    print_error "Docker daemon is not running. Please start Docker Desktop."
    exit 1
  fi
  print_success "Docker daemon is running"

  # Check docker-compose
  if ! command -v docker-compose &> /dev/null && ! docker compose version > /dev/null 2>&1; then
    print_error "docker-compose is not available."
    exit 1
  fi
  print_success "docker-compose is available"

  # Check .env file
  if [ ! -f "$ENV_FILE" ]; then
    print_warning ".env file not found at $ENV_FILE"
    print_info "Creating .env from .env.example..."
    if [ -f "$PROJECT_ROOT/.env.example" ]; then
      cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
      print_success ".env created from template"
      print_warning "Please update .env with your ICICI Breeze credentials and other settings."
    else
      print_error ".env.example not found. Cannot auto-create .env."
      exit 1
    fi
  else
    print_success ".env file exists"
  fi

  # Check docker-compose files
  if [ ! -f "$INFRA_DIR/docker-compose.yml" ]; then
    print_error "docker-compose.yml not found at $INFRA_DIR/docker-compose.yml"
    exit 1
  fi
  print_success "docker-compose.yml found"

  if [ ! -f "$INFRA_DIR/docker-compose.ui.yml" ]; then
    print_error "docker-compose.ui.yml not found at $INFRA_DIR/docker-compose.ui.yml"
    exit 1
  fi
  print_success "docker-compose.ui.yml found"
}

# ─────────────────────────────────────────────────────────────────────────────

build_services() {
  print_header "Building Docker Images"
  cd "$INFRA_DIR"
  docker-compose -f docker-compose.yml -f docker-compose.ui.yml build --no-cache
  print_success "All images built"
}

start_services() {
  print_header "Starting Services"

  cd "$INFRA_DIR"

  # Start with docker-compose (or docker compose if v2)
  if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
  else
    COMPOSE_CMD="docker compose"
  fi

  # Start both backend and UI services
  $COMPOSE_CMD -f docker-compose.yml -f docker-compose.ui.yml up -d

  print_success "All services started (background)"
}

# ─────────────────────────────────────────────────────────────────────────────

wait_for_services() {
  print_header "Waiting for Services to Be Healthy"

  local max_attempts=60
  local attempt=0
  local all_healthy=false

  while [ $attempt -lt $max_attempts ]; do
    attempt=$((attempt + 1))

    # Check backend services
    local backend_status=$(curl -s http://localhost:8010/health 2>/dev/null || echo "down")

    # Check UI
    local ui_status=$(curl -s http://localhost:3000 2>/dev/null && echo "up" || echo "down")

    if [ "$backend_status" != "down" ] && [ "$ui_status" = "up" ]; then
      all_healthy=true
      break
    fi

    echo -n "."
    sleep 2
  done

  echo ""

  if [ "$all_healthy" = true ]; then
    print_success "All services are healthy"
  else
    print_warning "Services are starting (may still be initializing)"
    print_info "Check logs with: ./start.sh logs"
  fi
}

# ─────────────────────────────────────────────────────────────────────────────

show_status() {
  print_header "Service Status"

  cd "$INFRA_DIR"

  if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
  else
    COMPOSE_CMD="docker compose"
  fi

  $COMPOSE_CMD -f docker-compose.yml -f docker-compose.ui.yml ps --no-trunc
}

# ─────────────────────────────────────────────────────────────────────────────

show_logs() {
  print_header "Service Logs (Last 50 lines, -f to follow)"

  cd "$INFRA_DIR"

  if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
  else
    COMPOSE_CMD="docker compose"
  fi

  # Parse arguments to check for -f (follow)
  if [[ "$@" == *"-f"* ]]; then
    $COMPOSE_CMD -f docker-compose.yml -f docker-compose.ui.yml logs -f
  else
    $COMPOSE_CMD -f docker-compose.yml -f docker-compose.ui.yml logs --tail=50
  fi
}

# ─────────────────────────────────────────────────────────────────────────────

stop_services() {
  print_header "Stopping Services"

  cd "$INFRA_DIR"

  if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
  else
    COMPOSE_CMD="docker compose"
  fi

  $COMPOSE_CMD -f docker-compose.yml -f docker-compose.ui.yml down

  print_success "All services stopped"
}

# ─────────────────────────────────────────────────────────────────────────────

show_help() {
  cat << EOF
${BLUE}SuryaDhana AI — Full Stack Startup${NC}

${YELLOW}Usage:${NC}
  ./start.sh [command]

${YELLOW}Commands:${NC}
  (no command)   Start all services (checks prerequisites, starts, waits for health)
  build          Rebuild all Docker images (no cache)
  stop           Stop all running services
  logs           Show last 50 lines of logs (add -f to follow in real-time)
  status         Show status of all running containers
  help           Show this help message

${YELLOW}Examples:${NC}
  ./start.sh                 # Start everything
  ./start.sh build           # Rebuild images
  ./start.sh logs -f         # Follow logs in real-time
  ./start.sh status          # Show container status
  ./start.sh stop            # Stop all services

${YELLOW}Access Points:${NC}
  Frontend:        http://localhost:3000
  API:             http://localhost:8010
  Gateway:         http://localhost:8000
  Redis:           localhost:6379

${YELLOW}Debugging:${NC}
  Check logs:      ./start.sh logs -f
  View status:     ./start.sh status
  Enter container: docker exec -it suryadhana_ai-ui-1 /bin/bash

EOF
}

# ─────────────────────────────────────────────────────────────────────────────

main() {
  case "${1:-}" in
    build)
      check_prerequisites
      build_services
      ;;
    stop)
      stop_services
      ;;
    logs)
      show_logs "${@:2}"
      ;;
    status)
      show_status
      ;;
    help)
      show_help
      ;;
    "")
      # Default: start everything
      check_prerequisites
      start_services
      wait_for_services
      print_header "✓ SuryaDhana AI is Running"
      echo -e "${GREEN}Frontend:     http://localhost:3000${NC}"
      echo -e "${GREEN}API:          http://localhost:8010${NC}"
      echo ""
      echo -e "${BLUE}Next Steps:${NC}"
      echo "  1. Open http://localhost:3000 in your browser"
      echo "  2. Navigate to 'System' tab to check service health"
      echo "  3. Use 'Broker Account' tab to connect to ICICI Breeze (if credentials in .env)"
      echo "  4. Use 'Backtest' tab with new T1/T2 (150-MA) filters"
      echo ""
      echo -e "${BLUE}Useful Commands:${NC}"
      echo "  ./start.sh logs -f      # Follow logs in real-time"
      echo "  ./start.sh status       # Check container status"
      echo "  ./start.sh stop         # Stop all services"
      echo "  ./start.sh help         # Show help"
      echo ""
      ;;
    *)
      print_error "Unknown command: $1"
      echo ""
      show_help
      exit 1
      ;;
  esac
}

# ─────────────────────────────────────────────────────────────────────────────

main "$@"
