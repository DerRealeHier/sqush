from werkzeug.routing import Rule
from routes.auth import auth_bp
from routes.main import main_bp
from routes.cart import cart_bp
from routes.checkout import checkout_bp
from routes.library import library_bp
from routes.social import social_bp
from routes.developer import developer_bp
from routes.messages import messages_bp
from routes.roadmap import roadmap_bp


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(social_bp)
    app.register_blueprint(developer_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(roadmap_bp)

    # Register legacy endpoint aliases for backward compatibility with templates and JS
    for rule in list(app.url_map.iter_rules()):
        if '.' in rule.endpoint:
            bare_name = rule.endpoint.split('.', 1)[1]
            if bare_name not in app.view_functions:
                app.view_functions[bare_name] = app.view_functions[rule.endpoint]
                new_rule = Rule(
                    rule.rule,
                    endpoint=bare_name,
                    methods=rule.methods,
                    defaults=rule.defaults,
                    subdomain=rule.subdomain,
                    strict_slashes=rule.strict_slashes,
                )
                app.url_map.add(new_rule)
