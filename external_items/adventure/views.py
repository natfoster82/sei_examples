from flask import Blueprint, render_template

adventure_bp = Blueprint('adventure', __name__, template_folder='templates', static_folder='static', url_prefix='/adventure')


@adventure_bp.route('')
def adventure():
    return render_template('adventure.html')
