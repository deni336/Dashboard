import os
import webbrowser
import platform
import subprocess
import threading
import asyncio
from flask import Flask, render_template, request, abort, jsonify, redirect, url_for, send_from_directory
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename
from waitress import serve
from config_manager import ConfigManager
from global_logger import GlobalLogger
from event_handler import EventHandler
from chat_client import ChatManager
from const import UPLOAD_FOLDER

class WebServer:
	def __init__(self):
		# Set up Flask app, logger, and config manager
		self.app = Flask(__name__, template_folder='../sites/templates', static_folder='../sites/static')
		self.app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
		self.sock = SocketIO(self.app, host='127.0.0.1', port=8000)
		self.logger = GlobalLogger.get_logger("WebServer")
		self.config = ConfigManager()
		self.event_handler = EventHandler()
		self.setup_routes()
		self.server_connect()
		asyncio.run(self.listen())

	def setup_routes(self):
		# Home route to fetch button names and send them to the frontend
		@self.app.route('/')
		def index():
			buttons_string = self.config.get('Application', 'buttons')
			self.buttons = [item.split(':')[0].strip() for item in buttons_string.split(',')]
			return render_template('index.html', buttons=self.buttons)
		
		@self.app.route('/resources/<path:filename>')
		def serve_resources(filename):
			full_path = f'/users/{os.getlogin()}/kasugai/resources'
			return send_from_directory(full_path, filename)

		# Route to dynamically save new buttons and return the updated button list as JSON
		@self.app.route('/save_buttons', methods=['POST'])
		def save_buttons():
			button_name = request.form['buttonName']
			button_link = request.form['buttonLink']
			
			# Fetch existing buttons and append the new one
			buttons_string = self.config.get('Application', 'buttons')
			new_button = f"{button_name}:{button_link}"
			if buttons_string:
				buttons_string += f",{new_button}"
			else:
				buttons_string = new_button

			# Save the updated button list back to the config
			self.config.set('Application', 'buttons', buttons_string)

			# Return updated button names to the frontend
			buttons = [item.split(':')[0].strip() for item in buttons_string.split(',')]
			return render_template('index.html', buttons=buttons)

		# Route to handle button click actions (either opening a URL or executing a file)
		@self.app.route('/button_click/<button_name>', methods=['POST'])
		def button_click(button_name):
			buttons_string = self.config.get('Application', 'buttons')
			# Convert the config buttons into a dictionary
			buttons = {item.split(':', 1)[0].strip(): item.split(':', 1)[1].strip() for item in buttons_string.split(',')}

			if button_name in buttons:
				link = buttons[button_name]
			# If the link is a URL, open it in a new browser tab
				if link.startswith('http://') or link.startswith('https://'):
						webbrowser.open_new_tab(link)
				else:
					# If the link is a file path, execute the file
					if os.path.exists(link):
						try:
							if platform.system() == "Windows":
									os.startfile(link)
							elif platform.system() == "Linux":
									subprocess.Popen(['xdg-open', link])
							elif platform.system() == "Darwin":
									subprocess.Popen(['open', link])
						except Exception as e:
							self.logger.error(f"Failed to execute {link}: {e}")
						return abort(500, description="Failed to execute the file.")
					else:
						return abort(404, description="File not found")
					return '', 204  # Return empty response with no content
			else:
				return abort(404, description="Button not found")
			
		@self.app.route('/change_background', methods=['POST'])
		def change_background():
			# Check if the post request has a file for the background image
			if 'backgroundImage' in request.files:
				file = request.files['backgroundImage']
			if file.filename != '':
					# Rename the uploaded file to 'bg.jpg'
					filename = secure_filename(file.filename)
					file.save(os.path.join(self.app.config['UPLOAD_FOLDER'], 'bg.jpg'))

			# Redirect or send a success message
			return redirect(url_for('index'))
		
		@self.app.route('/screenshare')
		def screen_share():
			return render_template('screenshare.html', buttons=self.buttons)
		
		@self.app.route('/send_message', methods=['POST'])
		def send_message():
			try:
				message = request.form.get('message')
				if not message:
					return jsonify({'error': 'Message content is missing'}), 400
				self.chat_manager.send_message(message)
				return jsonify({'status': 'Message sent successfully'}), 200
		
			except Exception as e:
				return jsonify({'error': str(e)}), 500

		# Route to shut down the server
		@self.app.route('/shutdown', methods=['POST'])
		def shutdown():
			self.shutdown_server()
			return "Server shutting down..."
		
	def server_connect(self):
		self.logger.info('Connecting to server...')
		self.chat_manager = ChatManager(server_address='127.0.0.1:8008')

	async def listen(self):
		"""
		Start the message listener and the user activity checker in separate threads.
		"""
		print("Starting ChatManager...")
		# Start a thread to listen for incoming messages
		
		message = await self.chat_manager.listen_for_messages()
		if message is not []:
			self.sock.emit('new_message', {
				'sender' : message.senderId,
				'content': message.content
			})

	def stop(self):
		"""
		Stop the chat manager from running.
		"""
		self.is_running = False
		print("ChatManager stopped.")


		
	def open_browser(self):
		# Open the default web browser to access the web server
		self.config = ConfigManager()
		port = self.config.getint('WebServer', 'port')
		url = f"http://{self.config.get('WebServer', 'address')}:{port}"
		browser = webbrowser.get('windows-default')  # Adjust as needed for different platforms
		browser.open(url)

	def run(self):
		# Start the web server using Waitress
		self.event_handler.register_event([os.getpid(), "WebServer"])
		self.config = ConfigManager()
		port = self.config.get('WebServer', 'port')
		self.logger.info(f'Starting WebServer using Waitress on port: {port}')
		if platform.system() == "Windows":
			self.open_browser()  # Automatically open the browser if on Windows
		serve(self.app, host=self.config.get('WebServer', 'address'), port=port)

	def shutdown_server(self):
		# Method to gracefully shut down the server
		pass
