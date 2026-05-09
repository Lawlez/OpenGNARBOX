DOCKER := docker
DOCKER_COMPOSE := docker-compose
# Set MOSH_VERSION so that stack yaml files pick up the correct labels
export MOSH_VERSION ?= $(shell /bin/bash ./mosh_version_prod)
export MACHINE := gbx2
export HOST_BIND_PROPAGATION := rslave
export DEV_INPUT := /dev/input
export DEV_DRI := /dev/dri
export DEV_DRI_RENDERD128 := $(shell ls /dev/dri/renderD128 2> /dev/null || echo /dev/null)
export DEV_DRI_CARD0 := $(shell ls /dev/dri/card0 2> /dev/null || echo /dev/null)
export REGISTRY ?= $(or $(shell cat /app_data/shiva/althing/docker_registry), docker.io)

.PHONY: up
up: configure-avahi up-network-ingress up-ingress-proxy up-services

up-network-ingress:## Create the overlay network
	$(DOCKER) network create -d overlay ingress-net || true

up-ingress-proxy: configure-avahi up-network-ingress ## Run the nginx reverse proxy
	cd stacks/mosh && $(DOCKER) stack deploy ingress_proxy -c ingress_proxy.yml

up-monitoring: ## Run the monitoring swarm
	cd stacks/mosh && $(DOCKER) stack deploy monitoring_stack -c monitoring_stack.yml

up-reporting: ## Run the reporting swarm
	cd stacks/mosh && $(DOCKER) stack deploy reporting_stack -c reporting_stack.yml

up-services: configure-avahi up-network-ingress ## Run the services swarm
	mkdir -p /app_data/auth
	mkdir -p /app_data/tokens
	mkdir -p /app_data/grypt
	@echo "Deploying mosh tag \"$(MOSH_VERSION)\""
	cd stacks/mosh && $(DOCKER) stack deploy services_stack -c services_stack_prod.yml

configure-avahi:
	-bash -c ". /sbin/libfirstboot.bash && avahi_service_setup"

.PHONY: down
down: down-reporting down-monitoring down-services down-ingress-proxy down-network-ingress

down-network-ingress: down-reporting down-monitoring down-services ## Remove the overlay network
	$(DOCKER) network rm ingress-net || true
down-ingress-proxy: down-reporting down-monitoring down-services ## Bring down the ingress proxy service
	$(DOCKER) stack rm ingress_proxy
down-monitoring: ## Bring down the monitoring swarm
	$(DOCKER) stack rm monitoring_stack
down-reporting: ## Bring down the reporting swarm
	$(DOCKER) stack rm reporting_stack
down-services: ## Bring down the services swarm
	$(DOCKER) stack rm services_stack

docker-purge: ## Purge everything docker-related in the app layer that isn't currently being used
	! docker service ls --format "{{.ID}}: {{.Mode}} {{.Replicas}}" | grep -q 0/1
	@echo "Purging because all replicas are 1/1"
	docker volume rm -f \$( docker volume ls -q ) &> /dev/null || true
	docker system prune -af --volumes &> /dev/null || true

.PHONY: pull
pull:
	@echo "Pulling mosh images tagged \"$(MOSH_VERSION)\" from $(REGISTRY)"
	$(DOCKER_COMPOSE) -f stacks/mosh/ingress_proxy.yml pull
	$(DOCKER_COMPOSE) -f stacks/mosh/services_stack_prod.yml pull

update-althing-host: ## Update althing-host services syslinkd and shivad
	@docker rm althing-host 2>/dev/null || true
	docker pull $(REGISTRY)/gnarbox/althing-host:$(MOSH_VERSION)
	docker create --name althing-host $(REGISTRY)/gnarbox/althing-host:$(MOSH_VERSION) sh
	rm -rf althing-host || true
	mkdir -p althing-host/etc
	docker cp althing-host:/app_data althing-host/
	docker cp althing-host:/etc/docker althing-host/etc
	docker cp althing-host:/etc/rundmc althing-host/etc
	docker cp althing-host:/usr althing-host/
	mv althing-host/usr/bin/* /usr/bin/
	mv althing-host/usr/lib/* /usr/lib/
	mv althing-host/etc/docker/* /etc/docker/
	mv althing-host/etc/rundmc/* /etc/rundmc/
	systemctl restart syslinkd
	systemctl restart shivad
	docker rm althing-host
	# Update ward on the Gnarbox host by copying from the ward image.
	docker pull $(REGISTRY)/gnarbox/ward:$(MOSH_VERSION)
	docker create --name ward $(REGISTRY)/gnarbox/ward:$(MOSH_VERSION) sh
	docker cp ward:/go/bin/ward /usr/bin/ward
	docker rm ward


.PHONY: help
help: ## Display this help screen
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%30s\033[0m  %s\n", $$1, $$2}'
