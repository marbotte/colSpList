from flask import Flask
from flask_restful import Api, Resource, abort
from endpoint_def import testEndem
from endpoint_def import testExot
from endpoint_def import testThreat
from endpoint_def import insertEndem
from endpoint_def import insertExot
from endpoint_def import insertThreat
from endpoint_def import insertTaxo


app = Flask(__name__, static_folder='static', static_url_path='')
api = Api(app)

@app.route('/')
def mainPage():
    return(app.send_static_file("home.html"))


api.add_resource(testEndem, '/testEndem')
api.add_resource(testExot, '/testExot')
api.add_resource(testThreat, '/testThreat')
api.add_resource(insertEndem, '/insertEndem')
api.add_resource(insertExot, '/insertExot')
api.add_resource(insertThreat, '/insertThreat')
api.add_resource(insertThreat, '/insertTaxo')

if __name__ == "__main__":
    app.run()