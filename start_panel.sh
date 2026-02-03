#!/bin/bash

ENV_FILE="env_file"
PANEL_PORT="5050"

# --- Helper Functions ---

log_info() {
    echo "Info: $1"
}

log_error() {
    echo "Error: $1"
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to setup firewall rule
setup_firewall() {
    if ! command_exists ufw || ! command_exists sudo; then
        echo "Warning: 'ufw' or 'sudo' not found. Skipping firewall setup." >&2
        return
    fi

    log_info "Allowing port $PANEL_PORT/tcp via UFW..."
    sudo ufw allow "$PANEL_PORT"/tcp comment "Allow Web Panel" >/dev/null 2>&1
}

# Function to cleanup firewall rule
cleanup_firewall() {
    if ! command_exists ufw || ! command_exists sudo; then
        return
    fi
    log_info "Cleaning up firewall rules..."
    # We run delete twice because UFW often creates separate v4 and v6 rules with the same comment
    sudo ufw delete allow "$PANEL_PORT"/tcp comment "Allow Web Panel" >/dev/null 2>&1
    sudo ufw delete allow "$PANEL_PORT"/tcp comment "Allow Web Panel" >/dev/null 2>&1
}

# --- Steps ---

check_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        log_info "Creating $ENV_FILE..."
        touch "$ENV_FILE"
        if [ $? -ne 0 ]; then
            log_error "Failed to create $ENV_FILE."
            return 1
        fi
    fi
    chmod 600 "$ENV_FILE"
}

install_dependencies() {
    log_info "Checking dependencies..."
    for pkg in python3-flask python3-structlog; do
        if ! dpkg -s $pkg > /dev/null 2>&1; then
            log_info "Installing $pkg..."
            sudo apt-get update -qq
            sudo apt-get install -yqq $pkg
            if [ $? -ne 0 ]; then
                # Fallback to pip if apt package doesn't exist
                log_info "Trying pip3 for ${pkg#python3-}..."
                pip3 install -q ${pkg#python3-}
            fi
        fi
    done
}

run_app() {
    # Navigate to the script directory
    cd "$(dirname "$0")"
    # Set PYTHONPATH to include the project root for shared_lib
    export PYTHONPATH=$PYTHONPATH:$(pwd)

    if [ -d "web_panel" ]; then
        log_info "Starting web panel on port $PANEL_PORT..."
        cd web_panel || return 1
        python3 app.py
        FLASK_EXIT_CODE=$?
        cd ..
        return $FLASK_EXIT_CODE
    else
        log_error "Directory 'web_panel' not found."
        return 1
    fi
}

# --- Main Execution ---

main() {
    echo "Starting Web Panel setup..."
    echo

    declare -A STEP_NAMES
    STEP_NAMES=(
        [check_env_file]="Configuring environment file"
        [setup_firewall]="Configuring firewall"
        [install_dependencies]="Installing dependencies"
        [run_app]="Running Web Panel"
    )

    local steps=(
        check_env_file
        setup_firewall
        install_dependencies
        run_app
    )

    for step in "${steps[@]}"; do
        echo "Step: ${STEP_NAMES[$step]}"
        if ! $step; then
            echo "Error: ${STEP_NAMES[$step]} failed."
            echo
            exit 1
        fi
        echo
        sleep 0.5
    done
}

# --- Setup Trap for Cleanup --- 
trap cleanup_firewall EXIT SIGINT SIGTERM

main
exit $?