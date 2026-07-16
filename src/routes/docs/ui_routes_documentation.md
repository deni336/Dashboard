# UI Routes Documentation

## Summary
The function `init_ui_routes` initializes the UI configuration and stable application resource folder used for appearance assets.

___
## Example Usage
```python
# Assuming `cfg` is a configuration object and `folder` is a directory path
init_ui_routes(cfg, '/path/to/resources')
```

___
## Code Analysis
### Inputs
- `cfg`: A configuration object or dictionary.
- `folder`: The fallback application resource directory. `[Application] resourcefolder` is read dynamically when available.
### Flow
1. The function takes two parameters: `cfg` and `folder`.
2. It assigns the value of `cfg` to the global variable `config`.
3. It stores `folder` as the fallback resource location. Relative configured paths are resolved beside `config.ini`, not against the process working directory.
### Outputs
- The function does not return any value; it modifies global variables.


## Summary
This code defines a Flask route for the root URL ('/'). It checks if a user profile exists in the session and redirects to a login page if not. If the profile exists, it retrieves a list of button names from a configuration and renders an HTML template with these buttons and the user profile.

___
## Example Usage
```python
# Assuming the Flask app is set up and running
# Accessing the root URL will trigger the `index` function
# If the session contains a 'profile', it will render 'index.html' with buttons
# Otherwise, it will redirect to the login page
```

___
## Code Analysis
### Inputs
- The session object, which may contain a 'profile' key.
- A configuration object with an 'Application' section containing a 'buttons' key.
### Flow
1. Check if 'profile' is in the session.
2. If not, redirect to the login route.
3. Retrieve the 'buttons' configuration string.
4. Parse the string into a list of button names.
5. Render the 'index.html' template with the button names and user profile.
### Outputs
- Redirects to the login page if 'profile' is not in the session.
- Renders 'index.html' with a list of buttons and the user profile if 'profile' is present.


## Summary
This authenticated route serves the active static JPG/JPEG, PNG, or WebP background from the same dedicated configured background directory used by the upload route. Background storage is separate from file-transfer downloads.

___
## Example Usage
```python
# With an authenticated session, this stable URL returns the active background.
response = requests.get('http://example.com/resources/background', cookies=session_cookies)
```

___
## Code Analysis
### Inputs
- `filename`: Must be `background`, or the legacy virtual alias `bg.jpg`; other resource names return 404.
### Flow
1. Require an authenticated Kasugai session.
2. Restrict the requested resource to the stable `/resources/background` URL or the legacy `/resources/bg.jpg` virtual alias.
3. Resolve the currently active image in `[Application] resourcefolder` and serve the actual JPG, PNG, or WebP file.
4. Return the image's native `image/jpeg`, `image/png`, or `image/webp` MIME type, with browser caching and MIME sniffing disabled. The legacy alias does not force JPEG content.
### Outputs
- Returns the saved background in its native format, or a 401/404 response when access or the filename is invalid.


## Summary
This route validates and saves an authenticated user's static JPG/JPEG, PNG, or WebP background upload, then returns a JSON result for the settings UI.

___
## Example Usage
```python
# Assuming `ui_bp` is initialized with `[Application] resourcefolder`
# To change the background image, send a POST request with a file named 'backgroundImage'
# Example using requests library:
import requests

url = 'http://example.com/change_background'
files = {'backgroundImage': open('path/to/image.jpg', 'rb')}
response = requests.post(url, files=files)
print(response.json())  # {"ok": true, "url": "/resources/background"}
```

___
## Code Analysis
### Inputs
- A POST request containing a file with the key 'backgroundImage'.
### Flow
1. Require an authenticated Kasugai session and a `backgroundImage` upload.
2. Accept `.jpg`/`.jpeg`, `.png`, and `.webp` files up to 20 MB and require the decoded format to match the selected extension.
3. Fully decode the image, reject animated, corrupt, or truncated content, and enforce a maximum decoded size of 40 megapixels.
4. Atomically publish the validated image in its native JPG, PNG, or WebP format without replacing the last known-good background when validation fails.
5. Return the stable `/resources/background` URL that the browser should preload and apply.
### Outputs
- Returns JSON success, or a specific JSON 4xx/5xx error without replacing the current background. Oversized, animated, mismatched, or corrupt files are rejected.


## Team Room deep links

The authenticated `/team-room` route opens Home with the unified Team Room
drawer. The legacy `/screenshare` route remains available for bookmarks and
opens that same drawer with its screen-sharing area expanded. Chat, file
transfer, and screen sharing are no longer rendered as separate pages or
top-level navigation tabs.

___
## Example Usage
```python
# Both routes require an authenticated session.
# /team-room redirects to /?team_room=open
# /screenshare redirects to /?team_room=open&screen=expanded
```

___
## Code Analysis
### Inputs
- The session, which must contain an authenticated `profile`.
### Flow
1. Check whether `profile` is present in the session.
2. If it is absent, redirect to the login route.
3. For `/team-room`, redirect to Home with `team_room=open`.
4. For `/screenshare`, redirect to Home with `team_room=open` and `screen=expanded`.
### Outputs
- Redirects to the login page if not logged in.
- Redirects authenticated users to Home, where the shared Team Room drawer is opened by query-string state.


