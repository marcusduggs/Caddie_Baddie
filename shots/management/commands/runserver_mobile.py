"""
Django management command to run the development server and display network URLs.
"""
import socket
from django.core.management.commands.runserver import Command as RunserverCommand
from django.core.management.base import CommandError


class Command(RunserverCommand):
    help = 'Runs the development server with network IP addresses displayed for mobile access'

    def get_local_ip(self):
        """Get the local IP address of this machine."""
        try:
            # Create a socket to determine the local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return None

    def inner_run(self, *args, **options):
        """Override inner_run to display custom startup message."""
        # Get the local IP
        local_ip = self.get_local_ip()
        
        # Get the port (default to 8000)
        addr = options.get('addrport', '')
        if ':' in addr:
            port = addr.split(':')[1]
        else:
            port = addr if addr else '8000'
        
        # Display startup message
        self.stdout.write("\n" + "="*70)
        self.stdout.write(self.style.SUCCESS("🏌️  Golf Caddie Server Started!"))
        self.stdout.write("="*70 + "\n")
        
        self.stdout.write(self.style.WARNING("📱 Access from your iPhone/iPad:"))
        if local_ip:
            self.stdout.write(self.style.HTTP_INFO(f"\n   ➜  Local Network:  http://{local_ip}:{port}/"))
        
        self.stdout.write(self.style.WARNING("\n💻 Access from this computer:"))
        self.stdout.write(self.style.HTTP_INFO(f"   ➜  Local:          http://127.0.0.1:{port}/"))
        self.stdout.write(self.style.HTTP_INFO(f"   ➜  Local:          http://localhost:{port}/"))
        
        self.stdout.write("\n" + self.style.WARNING("📝 Instructions:"))
        self.stdout.write("   1. Make sure your iPhone is on the same Wi-Fi network")
        if local_ip:
            self.stdout.write(f"   2. Open Safari on your iPhone and go to: http://{local_ip}:{port}/")
        self.stdout.write("   3. You can upload videos directly from your iPhone camera roll!")
        
        self.stdout.write("\n" + "="*70 + "\n")
        
        # Call the parent inner_run
        super().inner_run(*args, **options)
