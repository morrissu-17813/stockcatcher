from .core.engine import Tianji3KEngine

if __name__ == "__main__":
    engine = Tianji3KEngine()
    result = engine.run({})
    print(result.to_dict())
