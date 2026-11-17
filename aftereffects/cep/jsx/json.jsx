/* Small original ES3 JSON codec: no eval, Function, or native JSON dependency. */
var AEMCPJSON = (function () {
    function quote(s) {
        return '"' + s.replace(/["\\\x00-\x1f\u2028\u2029]/g, function (c) {
            var map = {'"':'\\"','\\':'\\\\','\b':'\\b','\f':'\\f','\n':'\\n','\r':'\\r','\t':'\\t'};
            return map[c] || '\\u' + ('0000' + c.charCodeAt(0).toString(16)).slice(-4);
        }) + '"';
    }
    function stringify(v, depth) {
        depth = depth || 0;
        if (depth > 40) throw new Error('JSON nesting too deep');
        if (v === null) return 'null';
        if (typeof v === 'string') return quote(v);
        if (typeof v === 'number') { if (!isFinite(v)) throw new Error('Nonfinite JSON'); return String(v); }
        if (typeof v === 'boolean') return String(v);
        var parts = [], i, k;
        if (v instanceof Array) {
            for (i = 0; i < v.length; i++) parts.push(stringify(v[i], depth + 1));
            return '[' + parts.join(',') + ']';
        }
        if (typeof v !== 'object') throw new Error('Unsupported JSON value');
        for (k in v) if (Object.prototype.hasOwnProperty.call(v, k)) parts.push(quote(k) + ':' + stringify(v[k], depth + 1));
        return '{' + parts.join(',') + '}';
    }
    function parse(s) {
        if (typeof s !== 'string' || s.length > 1048576) throw new Error('Invalid JSON input');
        var p = 0;
        function ws() { while (/[\x20\t\r\n]/.test(s.charAt(p)) && p < s.length) p++; }
        function string() {
            var out = '', c, h, escapes = {'"':'"','\\':'\\','/':'/','b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'};
            p++;
            while (p < s.length) {
                c = s.charAt(p++);
                if (c === '"') return out;
                if (c === '\\') {
                    c = s.charAt(p++);
                    if (c === 'u') { h = s.substr(p, 4); if (!/^[0-9a-fA-F]{4}$/.test(h)) throw new Error('Bad unicode escape'); out += String.fromCharCode(parseInt(h,16)); p += 4; }
                    else { if (!Object.prototype.hasOwnProperty.call(escapes,c)) throw new Error('Bad escape'); out += escapes[c]; }
                } else { if (c.charCodeAt(0) < 32) throw new Error('Control character'); out += c; }
            }
            throw new Error('Unterminated string');
        }
        function value(depth) {
            if (depth > 40) throw new Error('JSON nesting too deep');
            ws(); var c = s.charAt(p), v, k, m;
            if (c === '"') return string();
            if (c === '{' || c === '[') {
                var array = c === '['; v = array ? [] : {}; p++; ws();
                if (s.charAt(p) === (array ? ']' : '}')) { p++; return v; }
                while (true) {
                    ws();
                    if (array) v.push(value(depth + 1));
                    else {
                        if (s.charAt(p) !== '"') throw new Error('Expected key'); k = string(); ws();
                        if (k === '__proto__' || k === 'constructor' || k === 'prototype' || Object.prototype.hasOwnProperty.call(v,k)) throw new Error('Unsafe or duplicate key');
                        if (s.charAt(p++) !== ':') throw new Error('Expected colon'); v[k] = value(depth + 1);
                    }
                    ws(); c = s.charAt(p++);
                    if (c === (array ? ']' : '}')) return v;
                    if (c !== ',') throw new Error('Expected comma');
                }
            }
            var literals = ['true','false','null'], vals = [true,false,null], i;
            for (i=0;i<3;i++) if (s.substr(p,literals[i].length) === literals[i]) { p += literals[i].length; return vals[i]; }
            m = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(s.substr(p));
            if (!m) throw new Error('Invalid JSON value'); p += m[0].length; v = Number(m[0]);
            if (!isFinite(v)) throw new Error('Nonfinite number'); return v;
        }
        var result = value(0); ws(); if (p !== s.length) throw new Error('Trailing JSON'); return result;
    }
    return {parse:parse, stringify:stringify};
}());
