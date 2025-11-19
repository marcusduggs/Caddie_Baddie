#!/usr/bin/env python3
"""
Startup script for Golf Caddie - Mobile Access
Runs the Django server on 0.0.0.0 to allow iPhone/mobile access
"""
import os
import sys
import socket
import subprocess

def get_local_ip():
    """Get the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return None

def main():
    # Set Django settings module
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'golf_caddie.settings')
    
    # Get local IP
    local_ip = get_local_ip()
    port = "8000"
    
    # Display startup banner
    print("\n" + "="*70)
    print("🏌️  Golf Caddie - Mobile Access Server")
    print("="*70 + "\n")
    
    print("📱 Access from your iPhone/iPad:")
    if local_ip:
        print(f"   ➜  http://{local_ip}:{port}/")
        print(f"\n   📱 Open this URL in Safari on your iPhone")
    else:
        print("   ⚠️  Could not detect local IP address")
        print("   Run 'ifconfig' or 'ipconfig' to find your IP manually")
    
    print("\n💻 Access from this computer:")
    print(f"   ➜  http://localhost:{port}/")
    
    print("\n📝 Make sure:")
    print("   ✓ Your iPhone is on the same Wi-Fi network")
    print("   ✓ Firewall allows incoming connections on port " + port)
    
    print("\n" + "="*70)
    print("Starting Django development server...")
    print("Press CTRL+C to stop the server\n")
    
    # Run Django server on 0.0.0.0 to accept external connections
    try:
        subprocess.run([
            sys.executable,
            'manage.py',
            'runserver',
            f'0.0.0.0:{port}'
        ])
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped. Thank you for using Golf Caddie!")
        sys.exit(0)

if __name__ == '__main__':
    main()
