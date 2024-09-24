import os

from flask import Flask,render_template, jsonify, request, redirect, url_for, send_file, abort
from waitress import serve
from config_manager import ConfigManager
from global_logger import GlobalLogger

class WebServer:
   def __init__(self):
      self.app = Flask(__name__, template_folder='../sites/templates', static_folder='../sites/static')
      self.app.debug = True
      self.logger = GlobalLogger.get_logger("WebServer")
      self.config = ConfigManager()
      self.setup_routes()

   def setup_routes(self):
      @self.app.route('/')
      def index():
         # Get buttons from the config
         buttons_string = self.config.get('Application', 'buttons')
         buttons = []
         for item in buttons_string.split(','):
               name, link = item.split(':', 1)
               buttons.append({'name': name.strip(), 'link': link.strip()})
         return render_template('index.html', buttons=buttons)

      @self.app.route('/save_buttons', methods=['POST'])
      def save_buttons():
         # Get form data
         button_name = request.form['buttonName']
         button_link = request.form['buttonLink']
         
         # Get current buttons
         buttons_string = self.config.get('Application', 'buttons')

         # Add new button to the config string
         new_button = f"{button_name}:{button_link}"
         if buttons_string:
               buttons_string += f",{new_button}"
         else:
               buttons_string = new_button

         # Save to config
         self.config.set('Application', 'buttons', buttons_string)

         # Redirect back to index
         return redirect(url_for('index'))

      @self.app.route('/open_file/<path:filename>')
      def open_file(filename):
         # Define the path where files are located
         file_path = os.path.join("C:/Program Files/Docker/Docker/frontend/", filename)
         
         if os.path.exists(file_path):
               # Use Flask to serve the file
               return send_file(file_path)
         else:
               return abort(404, description="File not found")


      @self.app.route('/shutdown', methods=['POST'])
      def shutdown():
         self.shutdown_server()
         return "Server shutting down..."
    
   def run(self):
      self.config = ConfigManager()
      port = self.config.get('WebServer', 'port')
      self.logger.info(f'Starting WebServer using Waitress on port: {port}')
      serve(self.app, host=self.config.get('WebServer', 'address'), port=port)

   def shutdown_server(self):
      pass