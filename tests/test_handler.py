from lambda_function import lambda_handler


def test_basic_handler():
    response = lambda_handler({}, {})
    assert response["statusCode"] == 404
