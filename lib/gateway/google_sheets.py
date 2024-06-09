
"""
Module implements Gsheet API gateway.
"""
import logging
from typing import List, Optional

import google_auth_httplib2
import httplib2
import polars as pl
import retry
from apiclient import discovery
from google.oauth2 import service_account
from googleapiclient import errors as google_errors
from googleapiclient import http as google_http

from lib.gateway.base import rps_limiter
from lib.internal import timer

log = logging.getLogger("main_logger")

# Module constants
SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
SUPPORTED_POLARS_TYPES = {"Int64", "Float64", "Utf8", "Int32"}
# Request types
R_REQUEST = 1
W_REQUEST = 2


class GoogleSheetRetriableError(Exception):
    """
    Custom exception class to differentiate cases worth triggering a retry
    """
    def __init__(self, msg: str, og_exception: Exception):
        "Instantiates the exception"
        super().__init__(msg)
        self.og_exception = og_exception


class GoogleSheetMapper:
    "Encapsulates mapper methods that are used by GoogleSheetsGateway."

    @staticmethod
    def num_to_sheet_range(num: int) -> str:
        """
        Mapper converting col number to a spreadsheet column
        """
        rem, layers = num % 26, num // 26
        first = ""
        if layers > 0:
            first = chr(65+layers-1)
        return f"{first}{chr(65+rem-1)}"

    @staticmethod
    def _sheet_values_to_header_and_rows(sheet_values: list, header_rownum: int,
                                         header_offset: int) -> tuple:
        """
        Splits sheet_values into header and rows
        accounting for header_rownum and header_offset
        """
        header_index = header_rownum-1
        header = sheet_values[header_index]
        # Drop rows we want to skip based on params
        del sheet_values[header_index:header_rownum+header_offset]
        # All rows have values for all columns
        if (len(sheet_values) == 0
            or (hlen := len(header)) == len(sheet_values[0])):
            return header, sheet_values
        # Expand rows with None to achieve
        log.debug(
            "row data len %s does not match header len %s. Expanding...",
            len(sheet_values[0]), hlen
        )
        for row in sheet_values:
            for i in range(hlen-len(row)):
                row.append(None)
        return header, sheet_values
    
    @staticmethod
    def _sheet_schema_to_pl_aliases(schema: dict) -> list:
        """
        Converts sheet schema of form
            {
                "internal_col_name": {
                    "sheet_name": "CountryName",\n
                    "type": Polars type
                }
            }
        to a polars column aliases expression

        Args:
            schema: Nested dict of {col_key: {sheet_name, datatype}} form

        Returns:
            polars alias expression
        """
        return [pl.col(col_setup["sheet_name"]).alias(name=col)
                for col, col_setup in schema.items()]
    
    @staticmethod
    def _parse_col(df: pl.DataFrame, col: str, col_type: str) -> tuple:
        """
        Parses a single column of a polars df to a specified type

        Args:
            df: raw df with all columns being strings
            col: column to parse
            col_type: target type
        Returns:
             df with all columns properly typed
        """
        # Doing checks in advance to avoid unnecessary work
        if col_type not in SUPPORTED_POLARS_TYPES:
            return None, NotImplementedError(
                f"Type {col_type} is not supported"
            )
        if (dtype := getattr(pl, col_type, None)) is None:
            return None, TypeError(
                f"Column type {col_type} is a polars type"
            )
        # At this point know the column is of a supported type
        col_obj = pl.col(col)
        log.debug("Parsing %s column to type %s", col, dtype)
        df = df.with_columns(
            pl.when(col_obj == "")
            .then(pl.lit(value=None, dtype=dtype))
            .otherwise(col_obj)
            .alias(name=col)
        )
        log.debug("Filled empty strings with nulls")
        if col_type == "Utf8":
            return df, None
        elif "int" in col_type.lower():
            return df.with_columns(col_obj.cast(dtype=dtype)
                                   .alias(name=col)), None
        elif "float" in col_type.lower():
            return df.with_columns(
                col_obj.str.replace(pattern="%", value="", literal=True)
                .cast(dtype=dtype)
                .alias(name=col) / 100
            ), None

    def parse_cols(self, df: pl.DataFrame, schema: dict):
        "TODO"
        for col, col_setup in schema.items():
            try:
                df, e = self._parse_col(df=df, col=col,
                                        col_type=col_setup["type"])
                if e is not None:
                    log.error("Error parsing %s column: %s", col, e)
                    return None, e
            except Exception as e:
                log.error("Unhandled error parsing %s column: %s", col, e)
                return None, e
        return df, None

    def typecast_df(self, df: pl.DataFrame, schema: dict) -> tuple:
        """
        Typecasts df columns based on schema

        Args:
            df: polars df (untyped)
            schema: nested dict ala {internal_col_name: {sheet_name, type}}

        Returns:
            tuple(typed polars df, err if any)
        """
        log.debug("typecasting with schema %s", schema)
        try:
            pl_aliases = self._sheet_schema_to_pl_aliases(schema=schema)
        except Exception as e:
            log.error("Error parsing schema to aliases: %s", e)
            return None, e
        df = df.select(pl_aliases)
        log.debug("Parsing columns")
        return self.parse_cols(df=df, schema=schema)


    @staticmethod
    def _tab_name_to_tab_id(tab_name: str, tab_properties: dict):
        """
        Mapper converting tab name to tab id
        """
        log.debug("Looking tab id for %s in %s", tab_name, tab_properties)

        if (tab_data := tab_properties.get(tab_name, None)) is None:
            e = KeyError(f"{tab_name} is not present in: {tab_data}")
            log.debug("Error locating tab data for %s: %s", tab_name, e)
            return None, e

        log.debug("Located tab data: %s", tab_data)
        return tab_data["sheetId"], None

    @staticmethod
    def _delete_rows_params_to_body(tab_id: int, start: int, end: int) -> dict:
        """
        Mapper converting delete rows params to a request body that Google
        api understands.
        """
        return {
                    "deleteDimension": {
                        "range": {
                            "sheetId": tab_id,
                            "dimension": "ROWS",
                            "startIndex": start,
                            "endIndex": end
                        }
                    }
                }
    
    @staticmethod
    def _update_cell_params_to_body(rows: list, tab_id: int,
                                    start_row: int) -> dict:
        return {
            "updateCells": {
                "rows": rows,
                "fields": "*",
                "range": {
                    "sheetId": tab_id,
                    "startRowIndex": start_row,
                }
            }
        }

    @staticmethod
    def _df_to_rows_update(data: pl.DataFrame, include_header: bool) -> list:
        """
        Mapper converting df to a 2d list that Google understands
        """

        data_update = data.to_numpy().tolist()
        if include_header:
            data_update = [data.columns] + data_update

        rows_update = []
        for row in data_update:
            values = []
            for val in row:
                values.append({"userEnteredValue": {"stringValue": str(val)}})
            rows_update.append({"values": values})
        return rows_update

    @staticmethod
    def _append_cell_params_to_body(rows: list, tab_id: int) -> dict:
        return {
            "appendCells": {
                "rows": rows,
                "fields": "*",
                "sheetId": tab_id
            }
        }
    
    @staticmethod
    def parse_raw_properties(sheet_properties: dict):
        """
        Mapper converting raw response to from Google Sheets
        to a dict of {tab_name: properties} form
        """
        return {
            tab["properties"]["title"]: tab["properties"]
            for tab in sheet_properties["sheets"]
        }
    
    @staticmethod
    def _sheet_update_and_range_to_value_range(sheet_range: str,
                                               data_update: list) -> dict:
        """
        Mapper converting sheet data and data update
        to a value range JSON body
        """
        return {
            "range": sheet_range,
            "majorDimension": "ROWS",
            "values": data_update
        }
    
    def _df_to_update_range(self, data: pl.DataFrame, start_row: int):
        """
        Creates update range in AA:ZZ notation based on data & start row
        """
        return f"A{start_row}:{self.num_to_sheet_range(len(data.columns))}"


class GoogleSheetsGateway(GoogleSheetMapper):
    """
    Class for interacting with Google Sheets API.
    It's sync but can be used with Threading.
    """
    def __init__(self, service_acc_path: str, read_rps: float, write_rps: float,
                 read_concurrency: Optional[int] = None,
                 write_concurrency: Optional[int] = None,
                 request_timeout: Optional[int] = None,
                 api_version: Optional[str] = None):
        """Constructor of the class

        Args:
            service_acc_path: path to service account json file
            read_rps: rps for read operations
            write_rps: rps for write operations
            request_timeout: timeout for requests in seconds. Defaults to 60.
            read_concurrency: number of concurrent read requests. Defaults to None.
            write_concurrency: number of concurrent write requests. Defaults to None.
            api_version: _description_. Defaults to v4.
        """  # noqa: E501
        if api_version is None:
            api_version = "v4"
        if request_timeout is None:
            request_timeout = 60
        self.credentials = self._new_creds(service_acc_path=service_acc_path)

        # TODO abstract this? Do we even needs this as an attribute?
        # https://github.com/googleapis/google-api-python-client/issues/480
        authed_http = google_auth_httplib2.AuthorizedHttp(
            self.credentials, http=httplib2.Http(timeout=request_timeout)
        )
        self.gsheet_client = discovery.build(
                serviceName="sheets",
                version=api_version,
                http=authed_http
        )
        self.sheet_service = self.gsheet_client.spreadsheets()
        self.read_limiter = rps_limiter.ThreadingLimiter(
            rps=read_rps, concurrent_requests=read_concurrency
        )
        self.write_limiter = rps_limiter.ThreadingLimiter(
            rps=write_rps, concurrent_requests=write_concurrency
        )

    @staticmethod
    def _new_creds(service_acc_path: str) -> service_account.Credentials:
        """
        Helper instantiating credentials object for Google API authentication
        """
        return service_account.Credentials.from_service_account_file(
            filename=service_acc_path, scopes=SHEET_SCOPES
        )

    @retry.retry(exceptions=(GoogleSheetRetriableError,),
                 backoff=2, tries=10, delay=1, logger=log)
    def __make_request(self, req: google_http.HttpRequest,
                       rps_limiter: rps_limiter.ThreadingLimiter) -> dict:  # noqa: E501
        """
        Private method simplifying sending API requests to Google Backend.
        Has some basic retry logic.

        Args:
            req: request struct
        """
        log.debug("Calling %s method", req.methodId)
        try:
            with rps_limiter:
                with timer.TimerContext() as t:
                    res = req.execute()
            log.debug("Method %s responded in %s seconds", req.methodId, t.elapsed)
            return res
        except google_errors.HttpError as e:
            if  500 <= e.resp.status < 600:
                log.error(
                    "Got a retriable server error with code %s: %s",
                    e.resp.status, e
                )
                # Triggers a retry
                raise GoogleSheetRetriableError(
                    msg="Http error worth retrying", og_exception=e
                )
            raise e

    def _make_request(self, sheet_id: str, req: google_http.HttpRequest,
                      req_type: int) -> tuple:
        """
        Abstraction on top of __make_request that controls RPS limiting
        and handles exceptions.

        Args:
            req: request struct
            req_type: 1 for read, 2 for write

        Returns:
            tuple(response, err if any)
        """
        if req_type == R_REQUEST:
            limiter = self.read_limiter
        elif req_type == W_REQUEST:
            limiter = self.write_limiter
        else:
            return None, ValueError(
                f"Bad request type {req_type}. Need {R_REQUEST} or {W_REQUEST}"  # noqa: E501
            )
        log.debug("making request of type %s to sheet %s", req_type, sheet_id)  # noqa: E501
        try:
            return self.__make_request(req=req, rps_limiter=limiter), None
        except GoogleSheetRetriableError as e:
            log.error(
                "Request failed after retries with error %s. Response: %s",
                e.og_exception, e.og_exception.content
            )
            return None, e
        except Exception as e:
            log.error(
                "%s method returned a non-retriable error %s",
                req.methodId, e
            )
            return None, e
    
    def read_sheet(self, sheet_id: str, tab_name: str,
                   header_rownum: Optional[int] = None,
                   header_offset: Optional[int] = None,
                   as_df: Optional[bool] = None,
                   schema: Optional[dict] = None) -> tuple:
        """
        Reads sheet to a 2d list or a polars df

        Args:
            sheet_id: spreadsheet id
            tab_name: tab to read from in the sheet
            header_rownum: number of header row. Defaults to 1.
            header_offset: number of rows to skip after header. Defaults to 0.
            as_df: True means return as a polars df. Defaults to False.
            schema: nested dict of {col_name: {sheet_name, type} form.
                    Used for typing df. Defaults to {}.

        Returns:
            tuple(2d list or polars df, err if any)
        """
        if header_rownum is None:
            header_rownum = 1
        if header_offset is None:
            header_offset = 0
        if as_df is None:
            as_df = False
        if schema is None:
            schema = {}

        req = self.sheet_service.values().get(spreadsheetId=sheet_id,
                                              range=f"{tab_name}!A:ZZ",
                                              majorDimension="ROWS")
        resp, e = self._make_request(sheet_id=sheet_id,
                                     req=req, req_type=R_REQUEST)
        if e is not None:
            log.error("read_sheet error for sheet %s: %s", sheet_id, e)
            return None, e
        sheet_values = resp["values"]
        header, rows = self._sheet_values_to_header_and_rows(
            sheet_values=sheet_values,
            header_rownum=header_rownum,
            header_offset=header_offset
        )
        log.debug("Accounted for header row")
        if not as_df:
            log.debug("as_df is False, returning as 2d list")
            return [header] + rows, None

        log.debug("as_df is True, converting to polars")
        df = pl.DataFrame(data=rows, schema=header, orient="row")

        if not schema:
            log.debug("use_schema is False, returning untyped")
            return df, None
        return self.typecast_df(df=df, schema=schema)
    
    def batch_update(self, sheet_id: str, requests: List[dict]) -> tuple:
        """
        Performs a batch update operation using requests. Order matters.
        https://stackoverflow.com/questions/56049544/google-spreadsheet-api-batchupdate-request

        Args:
            sheet_id: spreadsheet id
            requests: list of bodies for batch operation

        Returns:
            tuple(response, err if any).
            Useful data is returned under replies key.
            TODO handle replies somehow?
        """
        req = self.sheet_service.batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": requests}
        )
        resp, e = self._make_request(sheet_id=sheet_id,
                                     req=req, req_type=W_REQUEST)
        if e is not None:
            log.error("err for sheet %s: %s", sheet_id, e)
            return None, e
        return resp, None
    
    def get_sheet_properties(self, sheet_id: str,
                             return_raw: Optional[bool] = None) -> tuple:
        "Fetches properties by sheet_id"
        if return_raw is None:
            return_raw = False
        req = self.sheet_service.get(spreadsheetId=sheet_id,
                                     includeGridData=False)
        data, e = self._make_request(sheet_id=sheet_id, req=req,
                                     req_type=R_REQUEST)
        if e is not None:
            log.error("error fetching properties for sheet %s", sheet_id)
            return None, e
        if return_raw:
            log.debug("parse_by_tab is False, returning raw properties")
            return data, e
        return self.parse_raw_properties(sheet_properties=data), None
    
    @staticmethod
    def _compute_number_of_rows_to_drop(current_len: int, new_len: int,
                                        row_limit: int):
        """
        Computes number of rows to delete to comply with row_limit
        """
        to_delete = 0
        if (tot_len := (current_len + new_len)) > row_limit:
            to_delete = tot_len - row_limit
        return to_delete
    
    def delete_rows(self, sheet_id: str, tab_name: str, end: int,
                    start: Optional[int] = None) -> Exception:
        "deletes rows from sheet"
        if start is None:
            start = 1
        sheet_props, e = self.get_sheet_properties(sheet_id=sheet_id,
                                                   return_raw=False)
        try:
            tab_id = sheet_props[tab_name]["sheetId"]
        except KeyError as e:
            log.error("deletion failed bc %s tab is not present in sheet %s",
                      tab_name,sheet_id)
            return e
        req_body = self._delete_rows_params_to_body(tab_id=tab_id, start=start, end=end)  # noqa: E501
        _, e = self.batch_update(sheet_id=sheet_id, requests=[req_body])
        if e is not None:
            log.error("deletion failed due to batch update error: %s", e)
            return e
    
    def append_data(self, sheet_id: str, tab_name: str,
                    data: pl.DataFrame, row_limit: int,
                    schema: Optional[dict] = None,
                    include_header: Optional[bool] = None) -> Exception:
        """Appends data to a sheeet

        Args:
            sheet_id (str): sheet identifier
            tab_name (str): tab name where to append
            data (pl.DataFrame): data to append
            row_limit (int): prevents sheets from growing indefinitely
            include_header (Optional[bool], optional): True includes data header in the append operation.

        Returns:
            Exception: error if any
        """  # noqa: E501
        if include_header is None:
            include_header = False
        
        curr_data, e = self.read_sheet(
            sheet_id=sheet_id,
            tab_name=tab_name,
            schema=schema,
            as_df=True
        )
        if e is not None:
            log.error("append failed bc reading sheet failed: %s", e)
            return e
        to_delete = self._compute_number_of_rows_to_drop(
            current_len=len(curr_data), new_len=len(data),
            row_limit=row_limit
        )
        log.debug("%s rows to delete", to_delete)
        sheet_props, e = self.get_sheet_properties(
            sheet_id=sheet_id, return_raw=False
        )
        # preserve order of columns by infering data from what's already in the sheet
        if schema is not None:
            data = data.select(curr_data.columns)
        else:
            data = data.select(curr_data[0])
        try:
            tab_id = sheet_props[tab_name]["sheetId"]
        except KeyError as e:
            log.error("deletion failed bc %s tab is not in sheet %s",
                      tab_name, sheet_id)
            return e
        batch_ops = [] # container for batch updates
        # delete if needed
        if to_delete > 0:
            batch_ops.append(
                self._delete_rows_params_to_body(
                    tab_id=tab_id, start=1, end=to_delete+1
                )
            )
        batch_ops.append(
            self._append_cell_params_to_body(
                rows=self._df_to_rows_update(
                    data=data,
                    include_header=include_header
                ),
                tab_id=tab_id
            )
        )
        _, e = self.batch_update(sheet_id=sheet_id, requests=batch_ops)
        if e is not None:
            log.error("append failed due to batch update error: %s", e)
            return e

        



