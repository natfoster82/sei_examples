from flask import Blueprint, render_template

connect4_bp = Blueprint('connect4', __name__, template_folder='templates', static_folder='static', url_prefix='/connect4')


@connect4_bp.route('')
def connect4():
    return render_template('connect4.html')
