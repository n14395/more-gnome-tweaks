export class BaseEffect {
    constructor(name) {
        this.name = name;
    }

    run(_actor, _config) {
        throw new Error(`${this.name} must implement run()`);
    }
}
