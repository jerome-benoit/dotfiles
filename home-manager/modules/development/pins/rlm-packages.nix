{
  ps,
  scipy,
  tyro,
}:
{
  beautifulsoup4 = ps.beautifulsoup4;
  httpx = ps.httpx;
  lxml = ps.lxml;
  numpy = ps.numpy;
  pandas = ps.pandas;
  pydantic = ps.pydantic;
  python-dotenv = ps.python-dotenv;
  pyyaml = ps.pyyaml;
  requests = ps.requests;
  inherit scipy;
  tomli = ps.tomli;
  inherit tyro;
}
