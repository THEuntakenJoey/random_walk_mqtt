.PHONY: up down restart clean logs ps

# Start core services in detached mode
up:
	docker compose up -d

# Graceful shutdown (collector automatically tears down all dynamically spawned devices first)
down:
	docker compose down

# Clean reset: stops stack and forcefully prunes any orphaned device containers and volumes
clean:
	docker compose down -v --remove-orphans
	@docker rm -f $$(docker ps -aq --filter "name=rw-device-") 2>/dev/null || true

# Rebuild and restart
restart: down up

# Stream logs
logs:
	docker compose logs -f

# Check container status across both static compose services and dynamic fleet
ps:
	@echo "=== Docker Compose Services ==="
	@docker compose ps
	@echo ""
	@echo "=== Dynamically Spawned Walkers ==="
	@docker ps --filter "name=rw-device-"
