import datetime
import hashlib
import hmac
import imghdr
import json
import logging
import mimetypes
import os
import requests
from requests.utils import guess_filename
from urlobject import URLObject as URL

FACEBOOK_API = 'https://graph.facebook.com'

logger = logging.getLogger(__name__)


class AdsAPIError(Exception):
    """
    Errors as defined in the Facebook documentation
    https://developers.facebook.com/docs/reference/ads-api/error-reference/
    """
    def __init__(self, data):
        self.error = data
        self.message = data['message']
        self.code = data['code']
        self.type = data['type']

    def __str__(self):
        return "AdsAPIError %s (%s): %s" % (self.code, self.type, self.message)


def file_tuple(f, default_name=None, image=True):
    """
    Returns a tuple suitable for requests file upload, particularly to enable
    Facebook APIs that require the content-type to be set.
    """
    # Same variable names as in RequestEncodingMixin._encode_files().
    fn, fp, ft, fh = None, None, None, None

    if isinstance(f, (tuple, list)):
        # Assign as many as provided.
        try:
            fn = f[0]
            fp = f[1]
            ft = f[2]
            fh = f[3]
        except IndexError:
            pass
    else:
        # As in requests, bare value is file pointer or content.
        fp = f

    if not fn:
        fn = guess_filename(fp) or default_name

    # Try to get content-type from filename first.
    if not ft and fn:
        ext = os.path.splitext(fn)[1].lower()
        ft = mimetypes.types_map.get(ext)

    # Fall back to detecting the image type from the header.
    if not ft and image:
        ext = None
        if isinstance(fp, basestring):
            ext = imghdr.what(None, fp[:32])
        elif callable(getattr(fp, 'seek', None)):
            try:
                ext = imghdr.what(fp)
            except IOError:  # unseekable file
                pass
        if ext:
            ft = mimetypes.types_map.get(ext)

    return fn, fp, ft, fh

    def __str__(self):
        return '(%s %s) %s' % (self.type, self.code, self.message)


class AdsAPI(object):
    """A client for the Facebook Ads API."""
    DATA_LIMIT = 100

    def __init__(self, access_token, app_id, app_secret):
        self.access_token = access_token
        self.app_id = app_id
        self.app_secret = app_secret
        h = hmac.new(access_token, app_secret, hashlib.sha256)
        self.appsecret_proof = h.hexdigest()

    def make_request(self, path, method, args=None, files=None, batch=False):
        """Makes a request against the Facebook Ads API endpoint."""
        args = dict(args or {})

        if batch:
            # Then just return a dict for the batch request
            return {
                'method': method,
                'relative_url': URL(path).set_query_params(args),
            }

        url = URL(FACEBOOK_API).relative(path)

        args.setdefault('access_token', self.access_token)

        if files and callable(getattr(files, 'items', None)):
            files = files.__class__((k, file_tuple(v, k)) for k, v in files.items())

        logger.debug('Making a %r request at %r with %r', method, url, args)
        if method == 'GET':
            r = requests.get(url.set_query_params(args))
        elif method == 'POST':
            r = requests.post(url, data=args, files=files)
        elif method == 'DELETE':
            r = requests.delete(url.set_query_params(args))

        if r.status_code == 200:
            return r.json()

        try:
            data = r.json()
        except ValueError:  # JSONDecodeError is a simplejson subclass
            r.raise_for_status()
        else:
            raise AdsAPIError(data)

    def make_batch_request(self, batch):
        """Makes a batched request against the Facebook Ads API endpoint."""
        args = dict(
            access_token=self.access_token,
            batch=json.dumps(batch),
        )

        logger.debug('Making a batched request with %r', args)
        r = requests.post(FACEBOOK_API, data=args)

        if r.status_code == 200:
            data = r.json()
            error_500 = {"error": {"code": 1, "message": "An unknown error occurred", "type": "UnknownError"}}
            data = [json.loads(d['body']) if d['code'] != 500 else error_500
                    for d in data]
            return data

        try:
            data = r.json()
        except ValueError:  # JSONDecodeError is a simplejson subclass
            r.raise_for_status()
        else:
            raise AdsAPIError(data)

    # New API
    def make_labeled_batch_request(self, batch):
        """Makes a batched request with label against the Facebook Ads API."""
        labels = batch.keys()
        queries = batch.values()
        data = self.make_batch_request(queries)
        return batch.__class__(zip(labels, data))

    def debug_token(self, token):
        """Returns debug information about the given token."""
        path = 'debug_token'
        args = {
            'input_token': token,
            'access_token': '%s|%s' % (self.app_id, self.app_secret)
        }
        return self.make_request(path, 'GET', args)

    def get_adusers(self, account_id, batch=False):
        """Returns the users of the given ad account."""
        path = 'act_%s/users' % account_id
        return self.make_request(path, 'GET', batch=batch)

    def get_adaccount(self, account_id, fields=None, batch=False):
        """Returns the fields of the given ad account."""
        path = 'act_%s' % account_id
        args = {'fields': fields} if fields else {}
        return self.make_request(path, 'GET', args, batch=batch)

    def get_adaccounts(self, user_id, fields, batch=False):
        """Returns the list of Facebook ad accounts."""
        path = '%s/adaccounts' % user_id
        args = {'fields': fields}
        return self.make_request(path, 'GET', args, batch=batch)

    # New API
    def get_adcampaign_group(self, campaign_group_id, fields, batch=False):
        """Return the fields for the given ad campaign group."""
        path = '%s' % campaign_group_id
        args = {'fields': fields}
        return self.make_request(path, 'GET', args, batch=batch)

    # New API
    def get_adcampaign_groups(self, account_id, fields, batch=False):
        """Returns the fields of all ad campaign groups
           from the given ad account."""
        path = 'act_%s/adcampaign_groups' % account_id
        args = {
            'fields': fields,
            'limit': self.DATA_LIMIT
        }
        return self.make_request(path, 'GET', args, batch=batch)

    # New API
    def delete_adcampaign_group(self, campaign_group_id, batch=False):
        """Delete specific campaign group."""
        path = '%s' % campaign_group_id
        return self.make_request(path, 'DELETE', batch=batch)

    def get_adcampaign(self, campaign_id, fields, batch=False):
        """Returns the fields for the given ad campaign."""
        path = '%s' % campaign_id
        args = {'fields': fields}
        return self.make_request(path, 'GET', args, batch=batch)

    # New API
    def get_adcampaigns_of_campaign_group(self, campaign_group_id, fields,
                                          batch=False):
        """Return the fields of all adcampaigns
           from the given adcampaign group."""
        path = '%s/adcampaigns' % campaign_group_id
        args = {'fields': fields}
        return self.make_request(path, 'GET', args, batch=batch)

    # New API
    def get_adcampaigns_of_account(self, account_id, fields, batch=False):
        """Returns the fields of all ad sets from the given ad account."""
        path = 'act_%s/adcampaigns' % account_id
        args = {'fields': fields}
        return self.make_request(path, 'GET', args, batch=batch)

    def get_adcampaigns(self, account_id, fields=None, batch=False):
        """Returns the fields of all ad sets from the given ad account."""
        return self.get_adcampaigns_of_account(account_id, fields, batch=batch)

    def get_adgroup(self, adgroup_id, fields=None, batch=False):
        """Returns the fields for the given ad group."""
        path = '%s' % adgroup_id
        args = {'fields': fields} if fields else {}
        return self.make_request(path, 'GET', args, batch=batch)

    def get_adgroups_by_adaccount(self, account_id, fields=None,
                                  status_fields=None, batch=False):
        """Returns the fields of all ad groups from the given ad account."""
        path = 'act_%s/adgroups' % account_id
        args = {'fields': fields} if fields else {}
        if status_fields:
            args['adgroup_status'] = status_fields
        return self.make_request(path, 'GET', args, batch=batch)

    def get_adgroups_by_adcampaign(self, campaign_id, fields=None,
                                   status_fields=None, batch=False):
        """Returns the fields of all ad groups from the given ad campaign."""
        path = '%s/adgroups' % campaign_id
        args = {'fields': fields} if fields else {}
        if status_fields:
            args['adgroup_status'] = status_fields
        return self.make_request(path, 'GET', args, batch=batch)

    def get_adcreative(self, creative_id, fields, batch=False):
        """Returns the fields for the given ad creative."""
        path = '%s' % creative_id
        args = {'fields': fields}
        return self.make_request(path, 'GET', args, batch=batch)

    def get_adcreatives(self, account_id, fields, batch=False):
        """Returns the fields for the given ad creative."""
        path = 'act_%s/adcreatives' % account_id
        args = {'fields': fields}
        return self.make_request(path, 'GET', args, batch=batch)

    def get_adimages(self, account_id, hashes=None, batch=False):
        """Returns the ad images for the given ad account."""
        path = 'act_%s/adimages' % account_id
        args = {}
        if hashes is not None:
            args = {'hashes': hashes}
        return self.make_request(path, 'GET', args, batch=batch)

    def get_stats_by_adaccount(self, account_id, batch=False):
        """Returns the stats for a Facebook campaign."""
        path = 'act_%s/adcampaignstats' % account_id
        return self.make_request(path, 'GET', batch=batch)

    # New API
    def get_stats_by_adcampaign_group(
            self, campaign_group_id, fields=None, filters=None, batch=False):
        """Returns the stats for a Facebook campaign group."""
        path = '%s/stats' % campaign_group_id
        args = {}
        if fields:
            args['fields'] = json.dumps(fields)
        if filters:
            args['filters'] = json.dumps(filters)
        return self.make_request(path, 'GET', args, batch=batch)

    def get_stats_by_adcampaign(self, account_id, campaign_ids=None,
                                batch=False):
        """Returns the stats for a Facebook campaign by adcampaign."""
        path = 'act_%s/adcampaignstats' % account_id
        args = {}
        if campaign_ids is not None:
            args['campaign_ids'] = json.dumps(campaign_ids)
        return self.make_request(path, 'GET', args, batch=batch)

    def get_stats_by_adgroup(self, account_id, adgroup_ids=None, batch=False):
        """Returns the stats for a Facebook campaign by adgroup."""
        path = 'act_%s/adgroupstats' % account_id
        args = {}
        if adgroup_ids is not None:
            args['adgroup_ids'] = json.dumps(adgroup_ids)
        return self.make_request(path, 'GET', args, batch=batch)

    # New API
    def get_time_interval(self, start, end):
        """Returns formatted time interval."""
        if not start or not end:
            return None
        end = end + datetime.timedelta(1)
        if not isinstance(start, datetime.datetime):
            start = datetime.datetime(start)
        if not isinstance(end, datetime.datetime):
            end = datetime.datetime(end)
        time_interval = dict(
            day_start=dict(day=start.day, month=start.month, year=start.year),
            day_stop=dict(day=end.day, month=end.month, year=end.year)
        )
        return json.dumps(time_interval)

    def get_adreport_stats(self, account_id, date_preset, time_increment,
                           data_columns, filters=None, actions_group_by=None,
                           batch=False):
        """Returns the ad report stats for the given account."""
        path = 'act_%s/reportstats' % account_id
        args = {
            'date_preset': date_preset,
            'time_increment': time_increment,
            'data_columns': json.dumps(data_columns),
        }
        if filters is not None:
            args['filters'] = json.dumps(filters)
        if actions_group_by is not None:
            args['actions_group_by'] = actions_group_by
        return self.make_request(path, 'GET', args, batch=batch)

    # New API
    def get_adreport_stats2(self, account_id, data_columns, date_preset=None,
                            date_start=None, date_end=None,
                            time_increment=None, actions_group_by=None,
                            filters=None, async=False, batch=False):
        """Returns the ad report stats for the given account."""
        if date_preset is None and date_start is None and date_end is None:
            raise BaseException("Either a date_preset or a date_start/end \
                                must be set when requesting a stats info.")
        path = 'act_%s/reportstats' % account_id
        args = {
            'data_columns': json.dumps(data_columns),
        }
        if date_preset:
            args['date_preset'] = date_preset
        if date_start and date_end:
            args['time_interval'] = \
                self.get_time_interval(date_start, date_end)
        if time_increment:
            args['time_increment'] = time_increment
        if filters:
            args['filters'] = json.dumps(filters)
        if actions_group_by:
            args['actions_group_by'] = json.dumps(actions_group_by)
        if async:
            args['async'] = 'true'
            return self.make_request(path, 'POST', args=args, batch=batch)
        return self.make_request(path, 'GET', args=args, batch=batch)

    # New API
    def get_async_job_status(self, job_id, batch=False):
        """Returns the asynchronously requested job status"""
        path = '%s' % job_id
        return self.make_request(path, 'GET', batch=batch)

    # New API
    def get_async_job_result(self, account_id, job_id, batch=False):
        """Returns completed result of the given async job"""
        path = 'act_%s/reportstats' % account_id
        args = {
            'report_run_id': job_id
        }
        return self.make_request(path, 'GET', args=args, batch=batch)

    def get_conversion_stats_by_adaccount(self, account_id, batch=False):
        """Returns the aggregated conversion stats for the given ad account."""
        path = 'act_%s/conversions' % account_id
        return self.make_request(path, 'GET', batch=batch)

    def get_conversion_stats_by_adcampaign(self, account_id, campaign_ids=None,
                                           include_deleted=False, batch=False):
        """Returns the conversions stats for all ad campaigns."""
        path = 'act_%s/adcampaignconversions' % account_id
        args = {}
        if campaign_ids is not None:
            args['campaign_ids'] = json.dumps(campaign_ids)
        if include_deleted is not None:
            args['include_deleted'] = include_deleted
        return self.make_request(path, 'GET', args, batch=batch)

    def get_conversion_stats_by_adgroup(self, account_id, adgroup_ids=None,
                                        include_deleted=False, batch=False):
        """Returns the conversions stats for all ad groups."""
        path = 'act_%s/adgroupconversions' % account_id
        args = {}
        if adgroup_ids is not None:
            args['adgroup_ids'] = json.dumps(adgroup_ids)
        if include_deleted is not None:
            args['include_deleted'] = include_deleted
        return self.make_request(path, 'GET', args, batch=batch)

    def get_conversion_stats(self, adgroup_id, batch=False):
        """Returns the conversion stats for a single ad group."""
        path = '%s/conversions' % adgroup_id
        return self.make_request(path, 'GET', batch=batch)

    def get_custom_audiences(self, account_id, audience_id, batch=False):
        """Returns the information for a given audience."""
        path = 'act_%s/customaudiences' % account_id
        return self.make_request(path, 'GET', batch=batch)

    def get_remarketing_pixel(self, account_id, batch=False):
        """Returns the remarketing pixel code for js."""
        path = 'act_%s/remarketingpixelcode' % account_id
        return self.make_request(path, 'GET', batch=batch)

    def get_offsite_pixel(self, offsite_pixel_id, batch=False):
        """Returns the information for the given offsite pixel."""
        path = '%s' % offsite_pixel_id
        return self.make_request(path, 'GET', batch=batch)

    def get_offsite_pixels(self, account_id, batch=False):
        """Returns the list of offsite pixels for the given account."""
        path = 'act_%s/offsitepixels' % account_id
        return self.make_request(path, 'GET', batch=batch)

    def get_keyword_stats(self, adgroup_id, batch=False):
        """Returns the keyword stats for the given ad group."""
        path = '%s/keywordstats' % adgroup_id
        return self.make_request(path, 'GET', batch=batch)

    def get_ratecard(self, account_id, batch=False):
        """Returns the rate card for Homepage Ads."""
        path = 'act_%s/ratecard' % account_id
        return self.make_request(path, 'GET', batch=batch)

    def get_reach_estimate(self, account_id, currency, targeting_spec,
                           creative_action_spec=None,
                           bid_for=None, batch=False):
        """Returns the reach estimate for the given currency and targeting."""
        path = 'act_%s/reachestimate' % account_id
        args = {
            'currency': currency,
            'targeting_spec': targeting_spec,
        }
        if creative_action_spec is not None:
            args['creative_action_spec'] = creative_action_spec
        if bid_for is not None:
            args['bid_for'] = bid_for
        return self.make_request(path, 'GET', args, batch=batch)

    def get_adcampaign_list(self, account_id):
        """Returns the list of ad campaigns and related data."""
        fields = 'id, name, campaign_status, start_time, end_time, ' \
                 'daily_budget, lifetime_budget, budget_remaining'
        batch = [
            self.get_adaccount(account_id, ['currency'], batch=True),
            self.get_adcampaigns(account_id, fields, batch=True),
            self.get_stats_by_adcampaign(account_id, batch=True),
        ]
        return self.make_batch_request(batch)

    def get_adcampaign_detail(self, account_id, campaign_id, date_preset):
        """Returns the detail of an ad campaign."""
        campaign_fields = [
            'name', 'campaign_status', 'daily_budget', 'lifetime_budget',
            'start_time', 'end_time']
        campaign_data_columns = [
            'campaign_name', 'reach', 'frequency', 'clicks',
            'actions', 'total_actions', 'ctr', 'spend']
        adgroup_data_columns = [
            'campaign_id', 'campaign_name', 'adgroup_id', 'adgroup_name',
            'reach', 'frequency', 'clicks', 'ctr', 'actions', 'cpm', 'cpc',
            'spend']
        demographic_data_columns = [
            'campaign_id', 'reach', 'frequency', 'clicks', 'actions', 'spend',
            'cpc', 'cpm', 'ctr', 'cost_per_total_action', 'age', 'gender']
        placement_data_columns = [
            'campaign_id', 'reach', 'frequency', 'clicks', 'actions', 'spend',
            'cpc', 'cpm', 'ctr', 'cost_per_total_action', 'placement']
        campaign_filters = [{
            'field': 'campaign_id', 'type': 'in', 'value': [campaign_id]}]
        batch = [
            self.get_adaccount(account_id, ['currency'], batch=True),
            self.get_adcampaign(campaign_id, campaign_fields, batch=True),
            self.get_adreport_stats(
                account_id, date_preset, 'all_days', campaign_data_columns,
                campaign_filters, ['action_type'], True),
            self.get_adreport_stats(
                account_id, date_preset, 1, campaign_data_columns,
                campaign_filters, None, True),
            self.get_adreport_stats(
                account_id, date_preset, 'all_days', adgroup_data_columns,
                campaign_filters, None, True),
            self.get_adreport_stats(
                account_id, date_preset, 'all_days', demographic_data_columns,
                campaign_filters, None, True),
            self.get_adreport_stats(
                account_id, date_preset, 'all_days', placement_data_columns,
                campaign_filters, None, True),
        ]
        return self.make_batch_request(batch)

    def get_user_pages(self, user_id, fields=None, batch=False):
        """Returns the list of pages to which user has access with tokens."""
        path = '%s/accounts' % user_id
        args = {}
        if fields:
            args['fields'] = json.dumps(fields)
        return self.make_request(path, 'GET', args, batch=batch)

    def get_autocomplete_data(self, q, type, want_localized_name=False,
                              list=None, limit=None, batch=False):
        """Returns the autocomplete data for the given query and type."""
        path = '%s/search' % q
        args = {'type': type}
        if want_localized_name:
            args['want_localized_name'] = want_localized_name
        if list:
            args['list'] = list
        if limit:
            args['limit'] = limit
        return self.make_request(path, 'GET', args, batch=batch)

    def get_page_access_token(self, page_id, batch=False):
        """Returns the page access token for the given page."""
        path = '%s' % page_id
        args = {'fields': 'access_token'}
        return self.make_request(path, 'GET', args, batch=batch)

    def create_link_page_post(self, page_id, link, message=None, picture=None,
                              thumbnail=None, name=None, caption=None,
                              description=None, published=None, batch=False):
        """Creates a link page post on the given page."""
        # TODO: this method is calling the API twice; combine them into batch
        page_access_token = self.get_page_access_token(page_id)
        path = '%s/feed' % page_id
        args = {
            'link': link,
            'access_token': page_access_token['access_token'],
        }
        files = {}
        if message is not None:
            args['message'] = message
        if picture is not None:
            args['picture'] = picture
        if thumbnail is not None:
            files['thumbnail'] = thumbnail
        if published is not None:
            args['published'] = published
        if name is not None:
            args['name'] = name
        if caption is not None:
            args['caption'] = caption
        if description is not None:
            args['description'] = description
        return self.make_request(path, 'POST', args, files, batch=batch)

    def create_video_page_post(self, page_id, source, title=None,
                               description=None, thumb=None, published=True,
                               scheduled_publish_time=None, batch=False):
        # TODO: this method is calling the API twice; combine them into batch
        page_access_token = self.get_page_access_token(page_id)
        path = '%s/videos' % page_id
        args = {
            'published': published,
            'access_token': page_access_token['access_token'],
        }
        files = {'source': source}
        if title is not None:
            args['title'] = title
        if description is not None:
            args['description'] = description
        if thumb is not None:
            files['thumb'] = thumb
        if scheduled_publish_time is not None:
            args['scheduled_publish_time'] = scheduled_publish_time
        return self.make_request(path, 'POST', args, files, batch=batch)

    # New API
    def create_adcampaign_group(self, account_id, name, campaign_group_status,
                                objective=None, batch=False):
        """Creates an ad campaign group for the given account."""
        path = 'act_%s/adcampaign_groups' % account_id
        args = {
            'name': name,
            'campaign_group_status': campaign_group_status,
        }
        if objective is not None:
            args['objective'] = objective
        return self.make_request(path, 'POST', args, batch=batch)

    # New API
    def update_adcampaign_group(self, campaign_group_id, name=None,
                                campaign_group_status=None, objective=None,
                                batch=False):
        """Updates condition of the given ad campaign group."""
        path = '%s' % campaign_group_id
        args = {}
        if name is not None:
            args['name'] = name
        if campaign_group_status is not None:
            args['campaign_group_status'] = campaign_group_status
        if objective is not None:
            args['objective'] = objective
        return self.make_request(path, 'POST', args, batch=batch)

    # New API: Need to change 'create_adcampaign' when facebook api is set new api.
    def _create_adcampaign(self, account_id, campaign_group_id, name,
                           campaign_status,
                           daily_budget=None, lifetime_budget=None,
                           start_time=None, end_time=None, batch=False):
        """Creates an ad campaign for the given account and
           the given campaign group."""
        if daily_budget is None and lifetime_budget is None:
            raise BaseException("Either a lifetime_budget or a daily_budget \
                                must be set when creating a campaign")
        if lifetime_budget is not None and end_time is None:
            raise BaseException("end_time is required when lifetime_budget \
                                is specified")
        path = 'act_%s/adcampaigns' % account_id
        args = {
            'campaign_group_id': campaign_group_id,
            'name': name,
            'campaign_status': campaign_status,
        }
        if daily_budget:
            args['daily_budget'] = daily_budget
        if lifetime_budget:
            args['lifetime_budget'] = lifetime_budget
        if start_time:
            args['start_time'] = start_time
        if end_time:
            args['end_time'] = end_time
        return self.make_request(path, 'POST', args, batch=batch)

    def create_adset(self, account_id, campaign_group_id, name,
                     campaign_status, daily_budget=None, lifetime_budget=None,
                     start_time=None, end_time=None, batch=False):
        """
        Creates an ad campaign for the given account and the campaign group.
        Functionality of this method is same as _create_adcampaign method.
        """
        return self._create_adcampaign(
            account_id, campaign_group_id, name, campaign_status,
            daily_budget, lifetime_budget, start_time, end_time, batch)

    # Deprecated: this method will be update.
    def create_adcampaign(self, account_id, name, campaign_status,
                          daily_budget=None, lifetime_budget=None,
                          start_time=None, end_time=None, batch=False):
        """
        Creates an ad campaign for the given account.
        Deprecated: This method cannot work on new campaign structure.
        """
        if daily_budget is None and lifetime_budget is None:
            raise BaseException("Either a lifetime_budget or a daily_budget \
                                 must be set when creating a campaign")
        if lifetime_budget is not None and end_time is None:
            raise BaseException("end_time is required when lifetime_budget \
                                is specified")
        path = 'act_%s/adcampaigns' % account_id
        args = {
            'name': name,
            'campaign_status': campaign_status,
        }
        if daily_budget:
            args['daily_budget'] = daily_budget
        if lifetime_budget:
            args['lifetime_budget'] = lifetime_budget
        if start_time:
            args['start_time'] = start_time
        if end_time:
            args['end_time'] = end_time
        return self.make_request(path, 'POST', args, batch=batch)

    # New API
    def update_adcampaign(self, campaign_id, name=None, campaign_status=None,
                          daily_budget=None, lifetime_budget=None,
                          end_time=None, batch=False):
        """Updates condition of the given ad campaign."""
        path = '%s' % campaign_id
        args = {}
        if name:
            args['name'] = name
        if campaign_status:
            args['campaign_status'] = campaign_status
        if daily_budget:
            args['daily_budget'] = daily_budget
        if lifetime_budget:
            args['lifetime_budget'] = lifetime_budget
        if end_time:
            args['end_time'] = end_time
        return self.make_request(path, 'POST', args, batch=batch)

    # New API
    def delete_adcampaign(self, campaign_id, batch=False):
        """Delete the given ad campaign."""
        path = '%s' % campaign_id
        return self.make_request(path, 'DELETE', batch=batch)

    def create_adcreative_type_27(self, account_id, object_id, body=None,
                                  auto_update=None, story_id=None,
                                  url_tags=None, name=None, batch=False):
        """Creates an ad creative in the given ad account."""
        path = 'act_%s/adcreatives' % account_id
        args = {
            'object_story_id': object_id,    # NEW AD CREATIVE MIGRATION
        }
        if url_tags:
            args['url_tags'] = url_tags
        if name:
            args['name'] = name
        return self.make_request(path, 'POST', args, batch=batch)

    def create_adgroup(self, account_id, name, bid_type, bid_info, campaign_id,
                       creative_id, targeting, max_bid=None, conversion_specs=None,
                       tracking_specs=None, view_tags=None, objective=None,
                       adgroup_status=None, batch=False):
        """Creates an adgroup in the given ad camapaign with the given spec."""
        path = 'act_%s/adgroups' % account_id
        args = {
            'name': name,
            'bid_type': bid_type,
            'bid_info': json.dumps(bid_info),
            'campaign_id': campaign_id,
            'creative': json.dumps({'creative_id': creative_id}),
            'targeting': json.dumps(targeting),
        }
        if max_bid:
            assert bid_type == 'CPM', 'can only use max_bid with CPM bidding'
            args['max_bid'] = max_bid
            del args['bid_info']  # get rid of bid_info
        if conversion_specs:
            args['conversion_specs'] = json.dumps(conversion_specs)
        if tracking_specs:
            args['tracking_specs'] = json.dumps(tracking_specs)
        if view_tags:
            args['view_tags'] = json.dumps(view_tags)
        if objective:
            args['objective'] = objective
        if adgroup_status:
            args['adgroup_status'] = adgroup_status
        return self.make_request(path, 'POST', args, batch=batch)

    def update_adgroup(self, adgroup_id, name=None, adgroup_status=None,
                       bid_type=None, bid_info=None, creative_id=None,
                       targeting=None, conversion_specs=None,
                       tracking_specs=None, view_tags=None, objective=None,
                       batch=False):
        """Updates condition of the given ad group."""
        path = "%s" % adgroup_id
        args = {}
        if name:
            args['name'] = name
        if bid_type:
            args['bid_type'] = bid_type
        if bid_info:
            args['bid_info'] = json.dumps(bid_info)
        if creative_id:
            args['creative'] = json.dumps({'creative_id': creative_id})
        if targeting:
            args['targeting'] = json.dumps(targeting)
        if conversion_specs:
            args['conversion_specs'] = json.dumps(conversion_specs)
        if tracking_specs:
            args['tracking_specs'] = json.dumps(tracking_specs)
        if view_tags:
            args['view_tags'] = json.dumps(view_tags)
        if objective:
            args['objective'] = objective
        if adgroup_status:
            args['adgroup_status'] = adgroup_status
        return self.make_request(path, 'POST', args, batch=batch)

    def create_custom_audience(self, account_id, name, subtype=None,
                               description=None, rule=None, opt_out_link=None,
                               retention_days=30, batch=False):
        """Create a custom audience for the given account."""
        path = "act_%s/customaudiences" % account_id
        args = {
            'name': name,
        }
        if subtype:
            args['subtype'] = subtype
        if description:
            args['description'] = description
        if rule:
            args['rule'] = json.dumps(rule)
        if opt_out_link:
            args['opt_out_link'] = opt_out_link
        if retention_days:
            args['retention_days'] = retention_days
        return self.make_request(path, 'POST', args, batch=batch)

    def create_custom_audience_from_website(
            self, account_id, name, domain, description=None,
            retention_days=30, batch=False):
        """Create a custom audience from website for the given account."""
        rule = {'url': {
            'i_contains': domain,
        }}
        return self.create_custom_audience(
            account_id, name, "WEBSITE", description=description, rule=rule,
            retention_days=retention_days, batch=batch)

    def create_lookalike_audiecne(self, account_id, name, audience_id,
                                  lookalike_spec, batch=False):
        """Create a lookalike audience for the given target audience."""
        path = "act_%s/customaudiences" % account_id
        args = {
            'name': name,
            'origin_audience_id': audience_id,
            'lookalike_spec': json.dumps(lookalike_spec),
        }
        return self.make_request(path, 'POST', args, batch)

    def create_offsite_pixel(self, account_id, name, tag, batch=False):
        """Creates an offsite pixel for the given account."""
        path = 'act_%s/offsitepixels' % account_id
        args = {
            'name': name,
            'tag': tag,
        }
        return self.make_request(path, 'POST', args, batch=batch)
