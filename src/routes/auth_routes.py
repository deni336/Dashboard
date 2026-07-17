from flask import Blueprint, redirect, render_template, request, session, url_for
from src.global_logger import GlobalLogger
from src.auth_manager import AuthManager, LicenseError

auth_bp = Blueprint('auth_bp', __name__)
logger = GlobalLogger.get_logger("AuthRoutes")


def init_auth_routes(app, config_handler, connect_callback):
    """
    Initialize DeniLicense authentication routes using AuthManager.
    """
    auth_manager = AuthManager(app, config_handler)

    @app.before_request
    def enforce_signed_license():
        if request.endpoint in {
            'auth_bp.login',
            'auth_bp.authorize',
            'auth_bp.logout',
            # Outbound workstation agents authenticate with a one-time pairing
            # code or revocable bearer token instead of a browser license
            # session. Keep this exemption exact; no route prefix is trusted.
            'workstation_bp.pair_workstation_agent',
            'workstation_bp.ingest_workstation_snapshot',
            'homelab_bp.pair_homelab_agent',
            'homelab_bp.ingest_homelab_snapshot',
            'homelab_bp.claim_homelab_action',
            'homelab_bp.submit_homelab_action_result',
            'launcher_bp.pair_launcher_agent',
            'launcher_bp.ingest_launcher_catalog',
            'launcher_bp.claim_launcher_run',
            'launcher_bp.submit_launcher_result',
            'static',
        }:
            return None
        if 'profile' not in session:
            if request.method == 'GET' and request.endpoint == 'project_bp.project_invitation':
                session['post_login_url'] = request.full_path.rstrip('?')
            return redirect(url_for('auth_bp.login'))
        try:
            license_session = auth_manager.validate_or_renew(session.get('denilicense'))
            session['denilicense'] = license_session
            session['profile']['license'] = license_session['claims']
            session.modified = True
        except LicenseError as exc:
            logger.warning(f"DeniLicense session rejected: {exc}")
            post_login_url = ''
            if request.method == 'GET' and request.endpoint == 'project_bp.project_invitation':
                post_login_url = request.full_path.rstrip('?')
            session.clear()
            session['license_error'] = str(exc)
            if post_login_url:
                session['post_login_url'] = post_login_url
            return redirect(url_for('auth_bp.login'))
        return None

    @auth_bp.route('/login', methods=['GET', 'POST'])
    def login():
        error = session.pop('license_error', None)
        submitted_email = ''
        if request.method == 'POST':
            submitted_email = request.form.get('email', '').strip()
            try:
                post_login_url = session.get('post_login_url', '')
                result = auth_manager.authenticate(
                    submitted_email,
                    request.form.get('password', ''),
                    request.form.get('claim_code', '').strip()
                )
                session.clear()
                session['profile'] = result['profile']
                session['denilicense'] = {
                    'licenseId': result['claims']['id'],
                    'activationId': result['claims']['activationId'],
                    'lease': result['lease'],
                    'claims': result['claims'],
                }
                connect_callback()
                if post_login_url.startswith('/') and not post_login_url.startswith('//'):
                    return redirect(post_login_url)
                return redirect(url_for('ui_bp.index'))
            except LicenseError as exc:
                logger.warning(f"DeniLicense login failed: {exc}")
                error = str(exc)
            except Exception as exc:
                logger.error(f"Unexpected DeniLicense login error: {exc}")
                error = "Unable to verify the license right now."

        return render_template(
            'login.html',
            error=error,
            product_code=auth_manager.product_code,
            api_url=auth_manager.api_url,
            submitted_email=submitted_email,
        )

    @auth_bp.route('/authorize')
    def authorize():
        return redirect(url_for('auth_bp.login'))

    @auth_bp.route('/logout', methods=['GET', 'POST'])
    def logout():
        session.pop('profile', None)
        session.pop('denilicense', None)
        return redirect(url_for('ui_bp.index'))
